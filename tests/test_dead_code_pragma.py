"""Tests for `# pragma: codegraph-public-api` opt-out from dead-code detection."""
from __future__ import annotations

import shutil
from pathlib import Path

import networkx as nx
import pytest

from codegraph.analysis import find_dead_code
from codegraph.graph.builder import GraphBuilder
from codegraph.graph.store_networkx import to_digraph
from codegraph.graph.store_sqlite import SQLiteGraphStore

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def pragma_graph(tmp_path: Path) -> nx.MultiDiGraph:
    repo = tmp_path / "repo"
    repo.mkdir()
    shutil.copytree(FIXTURES / "dead_code_pragma", repo / "pkg")
    store = SQLiteGraphStore(tmp_path / "graph.db")
    GraphBuilder(repo, store).build(incremental=False)
    g = to_digraph(store)
    store.close()
    return g


def _dead_qualnames(graph: nx.MultiDiGraph) -> set[str]:
    return {d.qualname for d in find_dead_code(graph)}


def _public_api_qualnames(graph: nx.MultiDiGraph) -> set[str]:
    out: set[str] = set()
    for _, attrs in graph.nodes(data=True):
        meta = attrs.get("metadata") or {}
        if meta.get("public_api"):
            qn = attrs.get("qualname")
            if qn:
                out.add(str(qn))
    return out


def test_function_with_canonical_pragma_not_flagged(
    pragma_graph: nx.MultiDiGraph,
) -> None:
    dead = _dead_qualnames(pragma_graph)
    assert not any(q.endswith(".marked_function") for q in dead)


def test_function_with_alternate_pragma_not_flagged(
    pragma_graph: nx.MultiDiGraph,
) -> None:
    dead = _dead_qualnames(pragma_graph)
    assert not any(q.endswith(".alt_marked_function") for q in dead)


def test_function_without_pragma_still_flagged(
    pragma_graph: nx.MultiDiGraph,
) -> None:
    """Regression: pragma must be required for the skip to apply."""
    dead = _dead_qualnames(pragma_graph)
    assert any(q.endswith(".unmarked_function") for q in dead)


def test_pragma_above_decorator_still_works(
    pragma_graph: nx.MultiDiGraph,
) -> None:
    dead = _dead_qualnames(pragma_graph)
    assert not any(q.endswith(".decorated_marked") for q in dead)


def test_unrelated_pragma_does_not_skip(
    pragma_graph: nx.MultiDiGraph,
) -> None:
    """A `# pragma: foo` comment must NOT exempt a function from dead-code."""
    dead = _dead_qualnames(pragma_graph)
    assert any(q.endswith(".looks_like_pragma") for q in dead)


def test_class_pragma_skips_class_only(
    pragma_graph: nx.MultiDiGraph,
) -> None:
    """A class-level pragma exempts the class node but NOT its methods.

    Methods carry their own pragma if the author wants them exempt.
    """
    dead = _dead_qualnames(pragma_graph)
    # The class itself is not flagged.
    assert not any(q.endswith(".MarkedClass") for q in dead)
    # An unmarked method on a marked class IS still flagged.
    assert any(q.endswith(".unmarked_method") for q in dead)


def test_method_with_pragma_not_flagged(
    pragma_graph: nx.MultiDiGraph,
) -> None:
    dead = _dead_qualnames(pragma_graph)
    assert not any(q.endswith(".marked_method") for q in dead)


def test_public_api_metadata_set(pragma_graph: nx.MultiDiGraph) -> None:
    """Sanity-check: the parser actually attaches the metadata flag."""
    flagged = _public_api_qualnames(pragma_graph)
    assert any(q.endswith(".marked_function") for q in flagged)
    assert any(q.endswith(".alt_marked_function") for q in flagged)
    assert any(q.endswith(".decorated_marked") for q in flagged)
    assert any(q.endswith(".MarkedClass") for q in flagged)
    assert any(q.endswith(".marked_method") for q in flagged)
    # Non-pragma symbols don't carry the flag.
    assert not any(q.endswith(".unmarked_function") for q in flagged)
    assert not any(q.endswith(".looks_like_pragma") for q in flagged)


def test_typescript_pragma_supported(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    shutil.copytree(FIXTURES / "dead_code_pragma", repo / "pkg")
    store = SQLiteGraphStore(tmp_path / "graph.db")
    GraphBuilder(repo, store).build(incremental=False)
    g = to_digraph(store)
    store.close()

    flagged: set[str] = set()
    for _, attrs in g.nodes(data=True):
        meta = attrs.get("metadata") or {}
        if meta.get("public_api"):
            qn = attrs.get("qualname")
            if qn:
                flagged.add(str(qn))
    assert any(q.endswith(".markedTsFunction") for q in flagged)
    assert not any(q.endswith(".unmarkedTsFunction") for q in flagged)


def test_synthetic_public_api_skip() -> None:
    """Direct unit-style test: a public_api node in a synthetic graph is skipped."""
    g: nx.MultiDiGraph = nx.MultiDiGraph()
    g.add_node(
        "fn::libcall",
        kind="FUNCTION",
        name="public_thing",
        qualname="pkg.public_thing",
        file="pkg/x.py",
        line_start=1,
        metadata={"public_api": True},
    )
    g.add_node(
        "fn::dead",
        kind="FUNCTION",
        name="private_thing",
        qualname="pkg.private_thing",
        file="pkg/x.py",
        line_start=10,
        metadata={},
    )
    dead = find_dead_code(g)
    ids = {d.id for d in dead}
    assert "fn::libcall" not in ids
    assert "fn::dead" in ids
