"""Tests for the cross-file CALLS resolver."""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from codegraph.graph.builder import GraphBuilder
from codegraph.graph.schema import EdgeKind, NodeKind
from codegraph.graph.store_sqlite import SQLiteGraphStore
from codegraph.resolve import resolve_unresolved_edges

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def built_repo(tmp_path: Path) -> tuple[Path, SQLiteGraphStore]:
    repo = tmp_path / "repo"
    repo.mkdir()
    shutil.copytree(FIXTURES / "python_sample", repo / "pkg")
    store = SQLiteGraphStore(tmp_path / "graph.db")
    GraphBuilder(repo, store).build(incremental=False)
    return repo, store


def test_build_runs_resolver_and_reduces_unresolved(
    built_repo: tuple[Path, SQLiteGraphStore],
) -> None:
    _repo, store = built_repo
    # The builder already resolved on first pass; ensure most CALLS edges
    # to in-repo functions are no longer prefixed with unresolved::.
    calls = list(store.iter_edges(kind=EdgeKind.CALLS))
    resolved = [e for e in calls if not e.dst.startswith("unresolved::")]
    assert resolved, "expected at least one resolved CALLS edge"


def test_resolver_links_self_method_calls(
    built_repo: tuple[Path, SQLiteGraphStore],
) -> None:
    _repo, store = built_repo
    nodes = {n.qualname: n for n in store.iter_nodes(kind=NodeKind.METHOD)}
    fetch = next(
        (n for q, n in nodes.items() if q.endswith("Dog.fetch")), None
    )
    speak = next(
        (n for q, n in nodes.items() if q.endswith("Dog.speak")), None
    )
    assert fetch is not None
    assert speak is not None
    edges = [
        e for e in store.iter_edges(src=fetch.id, kind=EdgeKind.CALLS)
        if e.dst == speak.id
    ]
    assert edges, "Dog.fetch should resolve self.speak() to Dog.speak"


def test_resolver_links_imported_call(
    built_repo: tuple[Path, SQLiteGraphStore],
) -> None:
    _repo, store = built_repo
    funcs = {n.qualname: n for n in store.iter_nodes(kind=NodeKind.FUNCTION)}
    read_file = next(
        (n for q, n in funcs.items() if q.endswith("utils.read_file")), None
    )
    count_words = next(
        (n for q, n in funcs.items() if q.endswith("utils.count_words")), None
    )
    assert read_file is not None
    assert count_words is not None
    edges = [
        e for e in store.iter_edges(src=read_file.id, kind=EdgeKind.CALLS)
        if e.dst == count_words.id
    ]
    assert edges, "read_file should resolve count_words() to utils.count_words"


def test_resolver_idempotent(
    built_repo: tuple[Path, SQLiteGraphStore],
) -> None:
    _repo, store = built_repo
    before = store.count_unresolved_edges()
    rs = resolve_unresolved_edges(store)
    after = store.count_unresolved_edges()
    assert after == before
    assert rs.resolved == 0


def test_delete_edge_removes_only_target(tmp_path: Path) -> None:
    from codegraph.graph.schema import Edge

    store = SQLiteGraphStore(tmp_path / "g.db")
    edges = [
        Edge(src="a", dst="b", kind=EdgeKind.CALLS),
        Edge(src="a", dst="c", kind=EdgeKind.CALLS),
    ]
    store.upsert_edges(edges)
    store.delete_edge("a", "b", EdgeKind.CALLS)
    remaining = list(store.iter_edges(src="a"))
    assert len(remaining) == 1
    assert remaining[0].dst == "c"
