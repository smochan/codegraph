"""Tests for the Go (tree-sitter) extractor.

Uses the fixture at ``tests/fixtures/go_sample/sample.go``. Exercises
every node/edge shape the parser emits — MODULE, CLASS (struct/interface),
FUNCTION, METHOD plus DEFINED_IN / IMPORTS / CALLS / INHERITS edges.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from codegraph.graph.schema import Edge, EdgeKind, Node, NodeKind
from codegraph.parsers.base import get_extractor_for
from codegraph.parsers.go import GoExtractor

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "go_sample"


@pytest.fixture(scope="module")
def parsed() -> tuple[list[Node], list[Edge]]:
    return GoExtractor().parse_file(FIXTURE_DIR / "sample.go", FIXTURE_DIR)


def _node(nodes: list[Node], name: str, kind: NodeKind | None = None) -> Node:
    """Find a node by name (and optionally kind). Helpful in assertions."""
    matches = [n for n in nodes if n.name == name]
    if kind is not None:
        matches = [n for n in matches if n.kind == kind]
    assert matches, f"no node named {name!r} (kind={kind})"
    return matches[0]


# ---------------------------------------------------------------------------
# Registration / dispatch
# ---------------------------------------------------------------------------


def test_extractor_registered_for_dot_go() -> None:
    """``.go`` files should resolve to the Go extractor via the registry."""
    ext = get_extractor_for(Path("foo/bar.go"))
    assert isinstance(ext, GoExtractor)


def test_returns_tuple_of_lists(parsed: tuple[list[Node], list[Edge]]) -> None:
    nodes, edges = parsed
    assert isinstance(nodes, list)
    assert isinstance(edges, list)
    assert all(isinstance(n, Node) for n in nodes)
    assert all(isinstance(e, Edge) for e in edges)


# ---------------------------------------------------------------------------
# Module / package
# ---------------------------------------------------------------------------


def test_emits_module_with_package_qualname(
    parsed: tuple[list[Node], list[Edge]],
) -> None:
    nodes, _ = parsed
    modules = [n for n in nodes if n.kind == NodeKind.MODULE]
    assert len(modules) == 1
    assert modules[0].qualname == "sample"
    assert modules[0].name == "sample"
    assert modules[0].language == "go"
    assert modules[0].metadata.get("package") == "sample"


# ---------------------------------------------------------------------------
# Imports
# ---------------------------------------------------------------------------


def test_imports_all_packages(
    parsed: tuple[list[Node], list[Edge]],
) -> None:
    """Each ``import "..."`` entry should produce one IMPORTS edge."""
    _, edges = parsed
    imports = [e for e in edges if e.kind == EdgeKind.IMPORTS]
    targets = {e.dst.replace("unresolved::", "") for e in imports}
    assert targets == {
        "fmt",
        "strings",
        "github.com/example/foo",
        "github.com/example/driver",
    }


def test_aliased_import_carries_alias_metadata(
    parsed: tuple[list[Node], list[Edge]],
) -> None:
    _, edges = parsed
    foo = next(
        e for e in edges
        if e.kind == EdgeKind.IMPORTS and "example/foo" in e.dst
    )
    assert foo.metadata.get("alias") == "custom"


# ---------------------------------------------------------------------------
# Types (struct + interface)
# ---------------------------------------------------------------------------


def test_struct_emitted_as_class(parsed: tuple[list[Node], list[Edge]]) -> None:
    nodes, _ = parsed
    greeter = _node(nodes, "Greeter", NodeKind.CLASS)
    assert greeter.qualname == "sample.Greeter"
    assert greeter.metadata.get("type_kind") == "struct_type"


def test_interface_emitted_as_class(parsed: tuple[list[Node], list[Edge]]) -> None:
    nodes, _ = parsed
    iface = _node(nodes, "Greetable", NodeKind.CLASS)
    assert iface.metadata.get("type_kind") == "interface_type"


def test_embedded_struct_produces_inherits_edge(
    parsed: tuple[list[Node], list[Edge]],
) -> None:
    """``type Polite struct { Greeter; ... }`` → INHERITS edge."""
    _, edges = parsed
    inherits = [e for e in edges if e.kind == EdgeKind.INHERITS]
    targets = {e.dst.replace("unresolved::", "") for e in inherits}
    assert "Greeter" in targets


# ---------------------------------------------------------------------------
# Functions
# ---------------------------------------------------------------------------


def test_top_level_function(parsed: tuple[list[Node], list[Edge]]) -> None:
    nodes, _ = parsed
    fn = _node(nodes, "NewGreeter", NodeKind.FUNCTION)
    assert fn.qualname == "sample.NewGreeter"
    params = fn.metadata.get("params", [])
    assert {p["name"] for p in params} == {"prefix"}
    assert params[0]["type"] == "string"


def test_function_defined_in_module(parsed: tuple[list[Node], list[Edge]]) -> None:
    nodes, edges = parsed
    fn = _node(nodes, "NewGreeter", NodeKind.FUNCTION)
    module = next(n for n in nodes if n.kind == NodeKind.MODULE)
    assert any(
        e.src == fn.id and e.dst == module.id and e.kind == EdgeKind.DEFINED_IN
        for e in edges
    )


# ---------------------------------------------------------------------------
# Methods
# ---------------------------------------------------------------------------


def test_method_carries_receiver_in_qualname(
    parsed: tuple[list[Node], list[Edge]],
) -> None:
    nodes, _ = parsed
    methods = [n for n in nodes if n.kind == NodeKind.METHOD]
    qualnames = {m.qualname for m in methods}
    assert "sample.Greeter.Greet" in qualnames
    assert "sample.Greeter.Shout" in qualnames


def test_method_receiver_metadata(parsed: tuple[list[Node], list[Edge]]) -> None:
    nodes, _ = parsed
    greet = next(
        n for n in nodes
        if n.kind == NodeKind.METHOD and n.qualname == "sample.Greeter.Greet"
    )
    assert greet.metadata["receiver"] == "Greeter"
    assert greet.metadata["receiver_pointer"] is True


def test_method_defined_in_points_at_receiver_type(
    parsed: tuple[list[Node], list[Edge]],
) -> None:
    """Methods should DEFINED_IN their receiver type, not the module."""
    nodes, edges = parsed
    greet = next(
        n for n in nodes
        if n.kind == NodeKind.METHOD and n.qualname == "sample.Greeter.Greet"
    )
    defined_in = [
        e for e in edges
        if e.src == greet.id and e.kind == EdgeKind.DEFINED_IN
    ]
    assert len(defined_in) == 1
    assert defined_in[0].dst == "unresolved::sample.Greeter"


# ---------------------------------------------------------------------------
# Calls
# ---------------------------------------------------------------------------


def test_bare_function_call(parsed: tuple[list[Node], list[Edge]]) -> None:
    """``Run`` calls ``NewGreeter()`` — bare-name call."""
    nodes, edges = parsed
    run_fn = _node(nodes, "Run", NodeKind.FUNCTION)
    targets = {
        e.dst.replace("unresolved::", "")
        for e in edges
        if e.src == run_fn.id and e.kind == EdgeKind.CALLS
    }
    assert "NewGreeter" in targets


def test_dotted_package_call(parsed: tuple[list[Node], list[Edge]]) -> None:
    """``Run`` calls ``custom.DoThing()`` and ``fmt.Println()``."""
    nodes, edges = parsed
    run_fn = _node(nodes, "Run", NodeKind.FUNCTION)
    targets = {
        e.dst.replace("unresolved::", "")
        for e in edges
        if e.src == run_fn.id and e.kind == EdgeKind.CALLS
    }
    assert "custom.DoThing" in targets
    assert "fmt.Println" in targets


def test_method_call_on_receiver(
    parsed: tuple[list[Node], list[Edge]],
) -> None:
    """``Shout`` calls ``g.Greet(name)`` — receiver-method call."""
    nodes, edges = parsed
    shout = next(
        n for n in nodes
        if n.kind == NodeKind.METHOD and n.qualname == "sample.Greeter.Shout"
    )
    targets = {
        e.dst.replace("unresolved::", "")
        for e in edges
        if e.src == shout.id and e.kind == EdgeKind.CALLS
    }
    # Should capture both receiver method + stdlib method.
    assert "g.Greet" in targets
    assert "strings.ToUpper" in targets


# ---------------------------------------------------------------------------
# Test-file detection
# ---------------------------------------------------------------------------


def test_test_file_emits_test_kind(tmp_path: Path) -> None:
    """``*_test.go`` files should produce TEST-kind module nodes."""
    test_file = tmp_path / "thing_test.go"
    test_file.write_text(
        "package thing\n\nfunc TestThing() {}\n"
    )
    nodes, _ = GoExtractor().parse_file(test_file, tmp_path)
    module = next(n for n in nodes if n.qualname == "thing")
    assert module.kind == NodeKind.TEST


# ---------------------------------------------------------------------------
# Defensive cases
# ---------------------------------------------------------------------------


def test_empty_file(tmp_path: Path) -> None:
    """A file with just a package clause should still produce a module node."""
    f = tmp_path / "empty.go"
    f.write_text("package empty\n")
    nodes, edges = GoExtractor().parse_file(f, tmp_path)
    assert len(nodes) == 1
    assert nodes[0].kind == NodeKind.MODULE
    assert nodes[0].qualname == "empty"
    assert edges == []


def test_unreadable_file_returns_empty(tmp_path: Path) -> None:
    """If the file can't be read, the parser should return empty results."""
    nodes, edges = GoExtractor().parse_file(
        tmp_path / "does-not-exist.go", tmp_path
    )
    assert nodes == []
    assert edges == []
