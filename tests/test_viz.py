"""Tests for codegraph.viz renderers."""
from __future__ import annotations

import shutil
from pathlib import Path

import networkx as nx
import pytest

from codegraph.graph.builder import GraphBuilder
from codegraph.graph.store_networkx import to_digraph
from codegraph.graph.store_sqlite import SQLiteGraphStore
from codegraph.viz import (
    GraphvizUnavailableError,
    render_html,
    render_mermaid,
    render_svg,
)

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


def test_mermaid_has_flowchart_and_classes(graph: nx.MultiDiGraph) -> None:
    out = render_mermaid(graph)
    assert out.startswith("flowchart LR")
    assert "classDef func" in out
    assert "classDef module" in out
    # at least one edge rendered
    assert "-->" in out or "-.->" in out or "==>" in out


def test_mermaid_clusters_by_file(graph: nx.MultiDiGraph) -> None:
    out = render_mermaid(graph, cluster_by_file=True)
    assert "subgraph " in out
    assert "end\n" in out or out.rstrip().endswith("end") or "    end" in out


def test_mermaid_no_cluster_disables_subgraphs(graph: nx.MultiDiGraph) -> None:
    out = render_mermaid(graph, cluster_by_file=False, show_legend=False)
    assert "subgraph " not in out


def test_html_writes_interactive_file(
    graph: nx.MultiDiGraph, tmp_path: Path
) -> None:
    out = tmp_path / "graph.html"
    result = render_html(graph, out)
    assert result == out
    assert out.exists()
    text = out.read_text()
    assert "<html" in text.lower()
    assert "vis" in text.lower()  # vis-network is bundled
    # at least one of our node ids should appear in the script
    sample_id = next(iter(graph.nodes()))
    assert sample_id in text


def test_svg_raises_when_dot_missing(
    graph: nx.MultiDiGraph, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Force missing graphviz package OR missing `dot` binary path.
    monkeypatch.setattr(
        "codegraph.viz.svg.shutil.which", lambda _name: None
    )
    out = tmp_path / "graph.svg"
    with pytest.raises(GraphvizUnavailableError):
        render_svg(graph, out)
