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


if __name__ == "__main__":  # pragma: no cover
    pytest.main([__file__, "-v"])
