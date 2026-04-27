"""Tests for resolver R3: conditional / union self-attribute binding.

R3 covers the backend-facade pattern where ``self.X`` is assigned in
multiple branches of ``__init__`` (different classes), or annotated with
a union type at the class level. The resolver must emit one CALLS edge
per concrete type so dead-code analysis can see all reachable
implementations.
"""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from codegraph.graph.builder import GraphBuilder
from codegraph.graph.schema import EdgeKind, NodeKind
from codegraph.graph.store_sqlite import SQLiteGraphStore

FIXTURES = Path(__file__).parent / "fixtures" / "resolver_r3"


def _build(tmp_path: Path, fixture_name: str) -> SQLiteGraphStore:
    repo = tmp_path / "repo"
    repo.mkdir()
    shutil.copy(FIXTURES / fixture_name, repo / fixture_name)
    store = SQLiteGraphStore(tmp_path / "graph.db")
    GraphBuilder(repo, store).build(incremental=False)
    return store


def _find_one(store: SQLiteGraphStore, *, kind: NodeKind, suffix: str):
    nodes = [
        n for n in store.iter_nodes(kind=kind) if n.qualname.endswith(suffix)
    ]
    assert len(nodes) == 1, (
        f"expected one {kind.value} ending with {suffix!r}, got "
        f"{[n.qualname for n in nodes]}"
    )
    return nodes[0]


def _calls_to(store: SQLiteGraphStore, dst_id: str) -> list:
    return [
        e for e in store.iter_edges(kind=EdgeKind.CALLS) if e.dst == dst_id
    ]


def test_r3_if_else_two_annotated_types(tmp_path: Path) -> None:
    """Both branches' methods must receive a CALLS edge from ``use``."""
    store = _build(tmp_path, "if_else_annotated.py")
    foo_method = _find_one(store, kind=NodeKind.METHOD, suffix=".Foo.method")
    bar_method = _find_one(store, kind=NodeKind.METHOD, suffix=".Bar.method")
    use = _find_one(store, kind=NodeKind.METHOD, suffix=".Facade.use")
    foo_calls = {e.src for e in _calls_to(store, foo_method.id)}
    bar_calls = {e.src for e in _calls_to(store, bar_method.id)}
    assert use.id in foo_calls, "expected CALLS Facade.use -> Foo.method"
    assert use.id in bar_calls, "expected CALLS Facade.use -> Bar.method"


def test_r3_if_else_same_annotation(tmp_path: Path) -> None:
    """Same annotation in both branches — annotation wins (one type)."""
    store = _build(tmp_path, "if_else_same_anno.py")
    base_run = _find_one(store, kind=NodeKind.METHOD, suffix=".Base.run")
    use = _find_one(store, kind=NodeKind.METHOD, suffix=".Facade.use")
    base_calls = {e.src for e in _calls_to(store, base_run.id)}
    assert use.id in base_calls, (
        "annotation 'Base' should resolve to Base.run regardless of "
        "constructor on RHS"
    )


def test_r3_class_union_pipe(tmp_path: Path) -> None:
    """``_b: Foo | Bar`` should bind ``self._b.method`` to both targets."""
    store = _build(tmp_path, "class_union_pipe.py")
    foo_method = _find_one(store, kind=NodeKind.METHOD, suffix=".Foo.method")
    bar_method = _find_one(store, kind=NodeKind.METHOD, suffix=".Bar.method")
    use = _find_one(store, kind=NodeKind.METHOD, suffix=".Holder.use")
    foo_calls = {e.src for e in _calls_to(store, foo_method.id)}
    bar_calls = {e.src for e in _calls_to(store, bar_method.id)}
    assert use.id in foo_calls
    assert use.id in bar_calls


def test_r3_class_union_typing(tmp_path: Path) -> None:
    """``_b: Union[Foo, Bar]`` syntax should bind both."""
    store = _build(tmp_path, "class_union_typing.py")
    foo_method = _find_one(store, kind=NodeKind.METHOD, suffix=".Foo.method")
    bar_method = _find_one(store, kind=NodeKind.METHOD, suffix=".Bar.method")
    use = _find_one(store, kind=NodeKind.METHOD, suffix=".Holder.use")
    foo_calls = {e.src for e in _calls_to(store, foo_method.id)}
    bar_calls = {e.src for e in _calls_to(store, bar_method.id)}
    assert use.id in foo_calls
    assert use.id in bar_calls


def test_r3_if_else_no_annotation_uses_constructor(tmp_path: Path) -> None:
    """No annotation: fall back to RHS constructor names from both branches."""
    store = _build(tmp_path, "if_else_no_anno.py")
    foo_method = _find_one(store, kind=NodeKind.METHOD, suffix=".Foo.method")
    bar_method = _find_one(store, kind=NodeKind.METHOD, suffix=".Bar.method")
    use = _find_one(store, kind=NodeKind.METHOD, suffix=".Facade.use")
    foo_calls = {e.src for e in _calls_to(store, foo_method.id)}
    bar_calls = {e.src for e in _calls_to(store, bar_method.id)}
    assert use.id in foo_calls
    assert use.id in bar_calls


def test_r3_single_branch_init_regression(tmp_path: Path) -> None:
    """Single ``self._svc: Service = Service()`` still resolves (R2 regress).
    """
    store = _build(tmp_path, "single_branch.py")
    run = _find_one(store, kind=NodeKind.METHOD, suffix=".Service.run")
    go = _find_one(store, kind=NodeKind.METHOD, suffix=".Handler.go")
    incoming = _calls_to(store, run.id)
    srcs = {e.src for e in incoming}
    assert go.id in srcs


def test_r3_walrus_does_not_crash(tmp_path: Path) -> None:
    """Walrus operator in __init__ is silently skipped (no crash)."""
    store = _build(tmp_path, "walrus.py")
    # Must successfully build a graph; presence of nodes is enough.
    nodes = list(store.iter_nodes(kind=NodeKind.CLASS))
    names = {n.name for n in nodes}
    assert "C" in names and "Foo" in names


def test_r3_missing_attr_no_phantom_edge(tmp_path: Path) -> None:
    """Calling a method on an undeclared self attribute emits no edge."""
    store = _build(tmp_path, "missing_attr.py")
    # No CALLS edge should resolve to a phantom 'method' target — there
    # is no Foo.method definition in this fixture, so any ``method`` edge
    # must remain unresolved or be absent.
    resolved_calls = [
        e for e in store.iter_edges(kind=EdgeKind.CALLS)
        if not e.dst.startswith("unresolved::")
        and "method" in (e.metadata.get("target_name") or "")
    ]
    assert resolved_calls == [], (
        f"unexpected resolved CALLS edges to phantom method: "
        f"{[(e.src, e.dst) for e in resolved_calls]}"
    )


if __name__ == "__main__":  # pragma: no cover
    pytest.main([__file__, "-v"])
