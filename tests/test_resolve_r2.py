"""Tests for resolver R2 false-positive fixes.

Each pattern has its own fixture under ``tests/fixtures/resolver_r2/``.
The fixtures are copied into a temporary repo and built end-to-end (via
``GraphBuilder``) so the resolver runs and we can assert the correct
CALLS edges land in the store.
"""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from codegraph.graph.builder import GraphBuilder
from codegraph.graph.schema import EdgeKind, NodeKind
from codegraph.graph.store_sqlite import SQLiteGraphStore

FIXTURES = Path(__file__).parent / "fixtures" / "resolver_r2"


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


def test_r2_same_file_constructor(tmp_path: Path) -> None:
    """Module-level ``Widget(...)`` calls should emit CALLS to the class."""
    store = _build(tmp_path, "same_file_ctor.py")
    widget = _find_one(store, kind=NodeKind.CLASS, suffix=".Widget")
    incoming = _calls_to(store, widget.id)
    assert incoming, (
        "expected at least one CALLS edge into Widget from the module-level "
        "list literal"
    )


def test_r2_nested_function_call(tmp_path: Path) -> None:
    """Calls inside nested ``def inner`` should attribute to ``inner``."""
    store = _build(tmp_path, "nested_call.py")
    helper = _find_one(store, kind=NodeKind.FUNCTION, suffix=".helper")
    inner = _find_one(store, kind=NodeKind.FUNCTION, suffix=".outer.inner")
    incoming = _calls_to(store, helper.id)
    srcs = {e.src for e in incoming}
    assert inner.id in srcs, (
        f"expected CALLS edge from nested 'inner' to 'helper'; got srcs="
        f"{srcs}"
    )


def test_r2_decorator_call(tmp_path: Path) -> None:
    """``@my_decorator(...)`` should emit a CALLS edge to my_decorator."""
    store = _build(tmp_path, "decorator_call.py")
    deco = _find_one(store, kind=NodeKind.FUNCTION, suffix=".my_decorator")
    incoming = _calls_to(store, deco.id)
    assert incoming, "expected CALLS edge from decorator usage to my_decorator"


def test_r2_class_annotation_self_chain(tmp_path: Path) -> None:
    """``self.svc.run()`` resolves via class-level annotation ``svc: Service``.
    """
    store = _build(tmp_path, "class_annotation.py")
    run = _find_one(store, kind=NodeKind.METHOD, suffix=".Service.run")
    go = _find_one(store, kind=NodeKind.METHOD, suffix=".Handler.go")
    incoming = _calls_to(store, run.id)
    srcs = {e.src for e in incoming}
    assert go.id in srcs, (
        f"expected CALLS edge from Handler.go to Service.run; got srcs={srcs}"
    )


def test_r2_instance_chain_method_call(tmp_path: Path) -> None:
    """``Builder().make()`` should emit a CALLS edge to Builder.make."""
    store = _build(tmp_path, "instance_chain.py")
    make = _find_one(store, kind=NodeKind.METHOD, suffix=".Builder.make")
    incoming = _calls_to(store, make.id)
    assert incoming, (
        "expected CALLS edge into Builder.make from Builder().make() chain"
    )


if __name__ == "__main__":  # pragma: no cover
    pytest.main([__file__, "-v"])
