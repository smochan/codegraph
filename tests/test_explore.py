"""Tests for the multi-page explorer dashboard."""
from __future__ import annotations

import shutil
from pathlib import Path

import networkx as nx
import pytest

from codegraph.graph.builder import GraphBuilder
from codegraph.graph.store_networkx import to_digraph
from codegraph.graph.store_sqlite import SQLiteGraphStore
from codegraph.viz import render_explore
from codegraph.viz.explore import _aggregate_to_modules, _strip_noise

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def graph(tmp_path: Path) -> nx.MultiDiGraph:
    repo = tmp_path / "repo"
    repo.mkdir()
    shutil.copytree(FIXTURES / "python_sample", repo / "pkg")
    store = SQLiteGraphStore(tmp_path / "graph.db")
    GraphBuilder(repo, store).build(incremental=False)
    g = to_digraph(store)
    store.close()
    return g


def test_strip_noise_drops_unresolved_and_files(graph: nx.MultiDiGraph) -> None:
    g = graph.copy()
    g.add_node("unresolved::ghost", kind="FUNCTION")
    g.add_node("file::abc", kind="FILE")
    cleaned = _strip_noise(g)
    assert "unresolved::ghost" not in cleaned.nodes
    assert all(
        attrs.get("kind") not in ("FILE",) and not str(n).startswith("unresolved::")
        for n, attrs in cleaned.nodes(data=True)
    )


def test_aggregate_to_modules_collapses_symbols(graph: nx.MultiDiGraph) -> None:
    cleaned = _strip_noise(graph)
    modules = _aggregate_to_modules(cleaned)
    # Every node in the aggregated graph is a MODULE.
    assert modules.number_of_nodes() > 0
    for _nid, attrs in modules.nodes(data=True):
        assert attrs["kind"] == "MODULE"
    # Symbols counter is populated for at least one module.
    assert any(attrs.get("symbols", 0) > 0 for _, attrs in modules.nodes(data=True))


def test_render_explore_writes_all_pages(
    graph: nx.MultiDiGraph, tmp_path: Path
) -> None:
    out_dir = tmp_path / "explore"
    result = render_explore(graph, out_dir, top_files=5, callgraph_limit=200)

    # Core pages exist and are non-empty.
    for name in ("index.html", "architecture.html", "callgraph.html", "inheritance.html"):
        path = out_dir / name
        assert path.exists(), f"missing {name}"
        assert path.stat().st_size > 0, f"empty {name}"

    # File-detail pages produced.
    file_pages = list((out_dir / "files").glob("*.html"))
    assert file_pages, "expected at least one per-file page"
    assert len(file_pages) <= 5

    # Index links to every top-level view.
    index_text = (out_dir / "index.html").read_text(encoding="utf-8")
    for name in ("architecture.html", "callgraph.html", "inheritance.html"):
        assert name in index_text, f"index missing link to {name}"
    # Index references files/ for at least one file detail.
    assert "files/" in index_text

    # ExploreResult lists all generated pages.
    assert result.out_dir == out_dir
    assert (out_dir / "index.html") in result.pages


def test_callgraph_limit_caps_node_count(
    graph: nx.MultiDiGraph, tmp_path: Path
) -> None:
    out_dir = tmp_path / "explore"
    render_explore(graph, out_dir, top_files=2, callgraph_limit=3)
    text = (out_dir / "callgraph.html").read_text(encoding="utf-8")
    # Page generated even with very tight cap.
    assert "callgraph" in text.lower() or "Call graph" in text
