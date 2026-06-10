"""C1: Python intra-procedural data-flow edges + PARAMETER nodes.

Tests cover:
* PARAMETER nodes emitted for each function param with PARAM_OF edges.
* DATA_ASSIGN: parameter → variable, variable → variable.
* DATA_ARG: in-scope variable to call-site sentinel (positional and keyword).
* DATA_RETURN: in-scope variable to function return sentinel.
* Call result assignment: DATA_ASSIGN from unresolved::ret::<callee>.
* Shadowing: two VARIABLE nodes with distinct line-qualified qualnames.
* Nested def: inner function variables do NOT leak into outer scope.
* Kill-switch: emit_data_edges=False suppresses all C1 edges/nodes.
"""
from __future__ import annotations

import shutil
import time
from pathlib import Path

import pytest

from codegraph.graph.schema import Edge, EdgeKind, Node, NodeKind
from codegraph.parsers.python import PythonExtractor

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run(tmp_path: Path, src: str, filename: str = "sample.py") -> tuple[list[Node], list[Edge]]:
    target = tmp_path / filename
    target.write_text(src)
    return PythonExtractor().parse_file(target, tmp_path)


def _data_edges(edges: list[Edge], kind: EdgeKind) -> list[Edge]:
    return [e for e in edges if e.kind == kind]


def _nodes_of_kind(nodes: list[Node], kind: NodeKind) -> list[Node]:
    return [n for n in nodes if n.kind == kind]


def _param_node(nodes: list[Node], param_name: str) -> Node | None:
    return next(
        (n for n in nodes if n.kind == NodeKind.PARAMETER and n.name == param_name),
        None,
    )


def _var_node(nodes: list[Node], var_name: str) -> Node | None:
    """Return first VARIABLE node with the given name (not a sentinel)."""
    return next(
        (
            n for n in nodes
            if n.kind == NodeKind.VARIABLE
            and n.name == var_name
            and not n.qualname.endswith(".<return>")
            and "synthetic_kind" not in n.metadata
        ),
        None,
    )


def _return_sentinel(nodes: list[Node], func_qualname: str) -> Node | None:
    expected_qualname = f"{func_qualname}.<return>"
    return next(
        (n for n in nodes if n.qualname == expected_qualname),
        None,
    )


# ---------------------------------------------------------------------------
# PARAMETER node emission
# ---------------------------------------------------------------------------


def test_param_nodes_emitted(tmp_path: Path) -> None:
    """Each function parameter gets a PARAMETER node."""
    src = "def f(a, b, c):\n    pass\n"
    nodes, _ = _run(tmp_path, src)
    params = _nodes_of_kind(nodes, NodeKind.PARAMETER)
    assert len(params) == 3
    names = {p.name for p in params}
    assert names == {"a", "b", "c"}


def test_param_node_qualnames(tmp_path: Path) -> None:
    """PARAMETER qualnames follow the <func>.<param:name> convention."""
    src = "def f(x):\n    pass\n"
    nodes, _ = _run(tmp_path, src)
    p = _param_node(nodes, "x")
    assert p is not None
    assert p.qualname == "sample.f.<param:x>"


def test_param_node_metadata(tmp_path: Path) -> None:
    """PARAMETER node metadata includes index, name, and type."""
    src = "def f(a, b: int):\n    pass\n"
    nodes, _ = _run(tmp_path, src)
    a = _param_node(nodes, "a")
    b = _param_node(nodes, "b")
    assert a is not None and a.metadata["index"] == 0 and a.metadata["type"] is None
    assert b is not None and b.metadata["index"] == 1 and b.metadata["type"] == "int"


def test_param_of_edges_emitted(tmp_path: Path) -> None:
    """Each PARAMETER node has a PARAM_OF edge pointing to the function."""
    src = "def f(a, b):\n    pass\n"
    nodes, edges = _run(tmp_path, src)
    param_of = _data_edges(edges, EdgeKind.PARAM_OF)
    assert len(param_of) == 2
    func_node = next(n for n in nodes if n.kind == NodeKind.FUNCTION)
    for e in param_of:
        assert e.dst == func_node.id


def test_param_count_matches_signature(tmp_path: Path) -> None:
    """PARAMETER node count equals the number of parameters (excluding self)."""
    src = "class C:\n    def m(self, x: str, y: int = 0):\n        pass\n"
    nodes, _ = _run(tmp_path, src)
    params = _nodes_of_kind(nodes, NodeKind.PARAMETER)
    # self is skipped, so only x and y
    assert len(params) == 2
    names = {p.name for p in params}
    assert names == {"x", "y"}


def test_variadic_param_nodes(tmp_path: Path) -> None:
    """Variadic *args / **kwargs also get PARAMETER nodes."""
    src = "def f(*args, **kwargs):\n    pass\n"
    nodes, _ = _run(tmp_path, src)
    params = _nodes_of_kind(nodes, NodeKind.PARAMETER)
    names = {p.name for p in params}
    assert "*args" in names
    assert "**kwargs" in names


# ---------------------------------------------------------------------------
# DATA_ASSIGN: param → variable
# ---------------------------------------------------------------------------


def test_param_to_variable_assign(tmp_path: Path) -> None:
    """def f(a): x = a  →  DATA_ASSIGN from PARAMETER a to VARIABLE x."""
    src = "def f(a):\n    x = a\n"
    nodes, edges = _run(tmp_path, src)
    a_param = _param_node(nodes, "a")
    x_var = _var_node(nodes, "x")
    assert a_param is not None
    assert x_var is not None
    assigns = _data_edges(edges, EdgeKind.DATA_ASSIGN)
    matching = [e for e in assigns if e.src == a_param.id and e.dst == x_var.id]
    assert len(matching) == 1


# ---------------------------------------------------------------------------
# DATA_ARG: positional and keyword
# ---------------------------------------------------------------------------


def test_data_arg_positional(tmp_path: Path) -> None:
    """f calls g(x) → DATA_ARG from VARIABLE x with position 0."""
    src = "def f(a):\n    x = a\n    g(x)\n"
    nodes, edges = _run(tmp_path, src)
    x_var = _var_node(nodes, "x")
    assert x_var is not None
    args = _data_edges(edges, EdgeKind.DATA_ARG)
    matching = [
        e for e in args
        if e.src == x_var.id and e.metadata.get("position") == 0
    ]
    assert len(matching) == 1
    assert matching[0].metadata["callee"] == "g"


def test_data_arg_kwarg(tmp_path: Path) -> None:
    """g(user=x) → DATA_ARG with kwarg='user'."""
    src = "def f(a):\n    x = a\n    g(user=x)\n"
    nodes, edges = _run(tmp_path, src)
    x_var = _var_node(nodes, "x")
    assert x_var is not None
    args = _data_edges(edges, EdgeKind.DATA_ARG)
    matching = [
        e for e in args
        if e.src == x_var.id and e.metadata.get("kwarg") == "user"
    ]
    assert len(matching) == 1
    assert matching[0].dst == "unresolved::arg::g::user"


def test_data_arg_param_directly(tmp_path: Path) -> None:
    """Passing a parameter directly: def f(a): g(a)."""
    src = "def f(a):\n    g(a)\n"
    nodes, edges = _run(tmp_path, src)
    a_param = _param_node(nodes, "a")
    assert a_param is not None
    args = _data_edges(edges, EdgeKind.DATA_ARG)
    matching = [e for e in args if e.src == a_param.id]
    assert len(matching) >= 1
    assert matching[0].metadata["position"] == 0


# ---------------------------------------------------------------------------
# DATA_RETURN
# ---------------------------------------------------------------------------


def test_data_return_from_variable(tmp_path: Path) -> None:
    """return x → DATA_RETURN from VARIABLE x to <return> sentinel."""
    src = "def f(a):\n    x = a\n    return x\n"
    nodes, edges = _run(tmp_path, src)
    x_var = _var_node(nodes, "x")
    ret_sentinel = _return_sentinel(nodes, "sample.f")
    assert x_var is not None
    assert ret_sentinel is not None
    returns = _data_edges(edges, EdgeKind.DATA_RETURN)
    matching = [e for e in returns if e.src == x_var.id and e.dst == ret_sentinel.id]
    assert len(matching) == 1


def test_data_return_from_param_directly(tmp_path: Path) -> None:
    """return a → DATA_RETURN directly from PARAMETER a."""
    src = "def f(a):\n    return a\n"
    nodes, edges = _run(tmp_path, src)
    a_param = _param_node(nodes, "a")
    assert a_param is not None
    returns = _data_edges(edges, EdgeKind.DATA_RETURN)
    assert any(e.src == a_param.id for e in returns)


# ---------------------------------------------------------------------------
# Call-result assignment: y = g(x) → DATA_ASSIGN from unresolved::ret::g
# ---------------------------------------------------------------------------


def test_call_result_data_assign(tmp_path: Path) -> None:
    """y = g(x) → DATA_ASSIGN from unresolved::ret::g to VARIABLE y."""
    src = "def f(a):\n    y = g(a)\n"
    nodes, edges = _run(tmp_path, src)
    y_var = _var_node(nodes, "y")
    assert y_var is not None
    assigns = _data_edges(edges, EdgeKind.DATA_ASSIGN)
    ret_assigns = [
        e for e in assigns
        if e.dst == y_var.id and e.src == "unresolved::ret::g"
    ]
    assert len(ret_assigns) == 1
    assert ret_assigns[0].metadata["callee"] == "g"


# ---------------------------------------------------------------------------
# Shadowing
# ---------------------------------------------------------------------------


def test_shadowing_produces_distinct_variable_nodes(tmp_path: Path) -> None:
    """x = a; x = b → two distinct VARIABLE nodes (line-qualified)."""
    src = "def f(a, b):\n    x = a\n    x = b\n"
    nodes, _edges = _run(tmp_path, src)
    x_vars = [
        n for n in nodes
        if n.kind == NodeKind.VARIABLE and n.name == "x"
    ]
    assert len(x_vars) == 2
    # They should have different qualnames (line-qualified).
    assert x_vars[0].qualname != x_vars[1].qualname


def test_shadowing_edges_point_correctly(tmp_path: Path) -> None:
    """Second assignment x = b should use PARAMETER b as source, not first x."""
    src = "def f(a, b):\n    x = a\n    x = b\n"
    nodes, edges = _run(tmp_path, src)
    b_param = _param_node(nodes, "b")
    a_param = _param_node(nodes, "a")
    assert b_param is not None and a_param is not None

    assigns = _data_edges(edges, EdgeKind.DATA_ASSIGN)
    # Find DATA_ASSIGN where source is PARAMETER b
    b_assigns = [e for e in assigns if e.src == b_param.id]
    assert len(b_assigns) >= 1
    # Find DATA_ASSIGN where source is PARAMETER a
    a_assigns = [e for e in assigns if e.src == a_param.id]
    assert len(a_assigns) >= 1
    # Destinations should be different VARIABLE nodes
    assert b_assigns[0].dst != a_assigns[0].dst


# ---------------------------------------------------------------------------
# Nested function: inner vars do NOT leak into outer scope
# ---------------------------------------------------------------------------


def test_nested_def_vars_do_not_leak(tmp_path: Path) -> None:
    """Inner function's variables are not added to the outer function's scope."""
    src = (
        "def outer(a):\n"
        "    def inner(b):\n"
        "        z = b\n"
        "    return a\n"
    )
    nodes, edges = _run(tmp_path, src)
    # outer should have a return sentinel (from 'return a')
    outer_ret = _return_sentinel(nodes, "sample.outer")
    assert outer_ret is not None

    # 'z' is inner's variable; outer's DATA_RETURN should only reference 'a'
    a_param = _param_node(nodes, "a")
    assert a_param is not None
    returns = _data_edges(edges, EdgeKind.DATA_RETURN)
    outer_returns = [e for e in returns if e.dst == outer_ret.id]
    assert len(outer_returns) >= 1
    # All sources of outer's return should be from 'a' (not 'z' or 'b')
    for e in outer_returns:
        assert e.src == a_param.id


def test_inner_function_has_its_own_params(tmp_path: Path) -> None:
    """Inner function emits its own PARAMETER nodes."""
    src = (
        "def outer(a):\n"
        "    def inner(b):\n"
        "        pass\n"
    )
    nodes, _ = _run(tmp_path, src)
    params = _nodes_of_kind(nodes, NodeKind.PARAMETER)
    param_names = {p.name for p in params}
    assert "a" in param_names
    assert "b" in param_names


# ---------------------------------------------------------------------------
# Kill-switch: emit_data_edges = False
# ---------------------------------------------------------------------------


def test_kill_switch_suppresses_data_edges(tmp_path: Path) -> None:
    """PythonExtractor.emit_data_edges=False suppresses all C1 edges/nodes."""
    src = "def f(a):\n    x = a\n    return x\n"
    target = tmp_path / "sample.py"
    target.write_text(src)
    extractor = PythonExtractor()
    extractor.__class__.emit_data_edges = False
    try:
        nodes, edges = extractor.parse_file(target, tmp_path)
    finally:
        extractor.__class__.emit_data_edges = True  # restore

    # No PARAMETER nodes
    params = _nodes_of_kind(nodes, NodeKind.PARAMETER)
    assert len(params) == 0
    # No data edges
    for kind in (EdgeKind.DATA_ASSIGN, EdgeKind.DATA_ARG, EdgeKind.DATA_RETURN, EdgeKind.PARAM_OF):
        assert len(_data_edges(edges, kind)) == 0


# ---------------------------------------------------------------------------
# Perf sanity: parse a larger file (codegraph/cli.py)
# ---------------------------------------------------------------------------


def test_parse_large_file_perf(tmp_path: Path) -> None:
    """Parsing a larger file completes in reasonable time.

    This is a rough sanity check — not a strict performance gate.
    The codegraph/cli.py is used as the test fixture (copied to tmp).
    """
    # Find cli.py relative to this repo.
    repo_root = Path(__file__).parent.parent
    cli_py = repo_root / "codegraph" / "cli.py"
    if not cli_py.exists():
        pytest.skip("cli.py not found — skipping perf sanity")

    dest = tmp_path / "cli.py"
    shutil.copy(cli_py, dest)

    extractor = PythonExtractor()

    # Baseline: without data edges
    extractor.__class__.emit_data_edges = False
    t0 = time.perf_counter()
    extractor.parse_file(dest, tmp_path)
    t_without = time.perf_counter() - t0

    # With data edges
    extractor.__class__.emit_data_edges = True
    t1 = time.perf_counter()
    nodes_with, edges_with = extractor.parse_file(dest, tmp_path)
    t_with = time.perf_counter() - t1

    data_edge_count = sum(
        1 for e in edges_with
        if e.kind in (EdgeKind.DATA_ASSIGN, EdgeKind.DATA_ARG, EdgeKind.DATA_RETURN)
    )
    param_node_count = sum(1 for n in nodes_with if n.kind == NodeKind.PARAMETER)

    # Must stay in the same order of magnitude (not 10x slower)
    assert t_with < max(t_without * 10, 1.0), (
        f"Data edge collection too slow: {t_without:.3f}s without vs {t_with:.3f}s with"
    )

    # Sanity: should produce data edges on a real file
    assert data_edge_count > 0, "Expected data edges on cli.py"
    assert param_node_count > 0, "Expected PARAMETER nodes on cli.py"


def test_for_loop_target_fed_by_iterable(tmp_path: Path) -> None:
    """``for url in scraped_urls`` → DATA_ASSIGN from iterable var to loop var."""
    nodes, edges = _run(
        tmp_path,
        "def f(scraped_urls):\n"
        "    for url in scraped_urls:\n"
        "        fetch(url)\n",
    )
    loop_vars = [
        n for n in nodes
        if n.kind == NodeKind.VARIABLE and n.name == "url"
    ]
    assert len(loop_vars) == 1
    assert loop_vars[0].metadata.get("loop_target") is True
    # iterable (PARAMETER scraped_urls) feeds the loop var
    param = next(
        n for n in nodes
        if n.kind == NodeKind.PARAMETER and n.name == "scraped_urls"
    )
    assign = [
        e for e in edges
        if e.kind == EdgeKind.DATA_ASSIGN
        and e.src == param.id and e.dst == loop_vars[0].id
    ]
    assert assign, "expected DATA_ASSIGN from iterable param to loop target"
    # and the loop var flows into the fetch() call argument
    arg = [
        e for e in edges
        if e.kind == EdgeKind.DATA_ARG and e.src == loop_vars[0].id
    ]
    assert arg, "expected DATA_ARG from loop var into fetch()"
