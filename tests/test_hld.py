"""Tests for the hand-rolled HLD view."""
from __future__ import annotations

import shutil
from pathlib import Path

import networkx as nx
import pytest

from codegraph.graph.builder import GraphBuilder
from codegraph.graph.store_networkx import to_digraph
from codegraph.graph.store_sqlite import SQLiteGraphStore
from codegraph.viz.hld import LAYERS, build_hld

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def codegraph_repo_graph() -> nx.MultiDiGraph:
    """Build the graph for codegraph itself (the only repo HLD targets)."""
    repo_root = Path(__file__).resolve().parent.parent
    db_path = repo_root / ".codegraph" / "graph.db"
    if not db_path.exists():
        pytest.skip("codegraph repo graph not built yet")
    store = SQLiteGraphStore(db_path)
    g = to_digraph(store)
    store.close()
    return g


@pytest.fixture
def fixture_graph(tmp_path: Path) -> nx.MultiDiGraph:
    repo = tmp_path / "repo"
    repo.mkdir()
    shutil.copytree(FIXTURES / "python_sample", repo / "pkg")
    store = SQLiteGraphStore(tmp_path / "graph.db")
    GraphBuilder(repo, store).build(incremental=False)
    g = to_digraph(store)
    store.close()
    return g


def test_hld_returns_all_layers(fixture_graph: nx.MultiDiGraph) -> None:
    hld = build_hld(fixture_graph)
    # Even on a non-codegraph fixture the layer list itself is always returned.
    assert [L["id"] for L in hld.layers] == [L.id for L in LAYERS]
    assert "metrics" in hld.__dict__ or hasattr(hld, "metrics")


def test_hld_layered_mermaid_is_valid(fixture_graph: nx.MultiDiGraph) -> None:
    hld = build_hld(fixture_graph)
    # Even with no codegraph modules in the fixture, the function must
    # produce a syntactically valid Mermaid header.
    assert hld.mermaid_layered.startswith("flowchart TB")
    assert hld.mermaid_context.startswith("flowchart LR")


def test_hld_classifies_codegraph_modules(
    codegraph_repo_graph: nx.MultiDiGraph,
) -> None:
    hld = build_hld(codegraph_repo_graph)
    # Every layer should have at least one module on the actual codegraph repo.
    populated = {lid for lid, comps in hld.components.items() if comps}
    expected = {"cli", "pipeline", "parsers", "resolve", "storage",
                "analysis", "viz"}
    assert expected <= populated, f"missing layers: {expected - populated}"

    # Sanity-check obvious placements.
    cli_qns = [c["qualname"] for c in hld.components["cli"]]
    assert "codegraph.cli" in cli_qns
    pipeline_qns = [c["qualname"] for c in hld.components["pipeline"]]
    assert "codegraph.graph.builder" in pipeline_qns
    storage_qns = [c["qualname"] for c in hld.components["storage"]]
    assert any(qn.startswith("codegraph.graph.store_") for qn in storage_qns)


def test_hld_cross_layer_edges_have_weights(
    codegraph_repo_graph: nx.MultiDiGraph,
) -> None:
    hld = build_hld(codegraph_repo_graph)
    assert hld.edges, "expected cross-layer edges on real repo"
    for e in hld.edges:
        assert e["source"] != e["target"]
        assert e["weight"] >= 1
        assert e["kind"] in ("CALLS", "IMPORTS")
    # The layered Mermaid embeds at least one labeled inter-layer arrow.
    assert "-->" in hld.mermaid_layered
    assert "linkStyle" in hld.mermaid_layered


def test_hld_metrics_are_consistent(
    codegraph_repo_graph: nx.MultiDiGraph,
) -> None:
    hld = build_hld(codegraph_repo_graph)
    m = hld.metrics
    assert m["components"] == sum(len(v) for v in hld.components.values())
    assert m["cross_layer_edges"] == len(hld.edges)
    assert m["total_cross_layer_calls"] == sum(
        int(e["weight"]) for e in hld.edges if e["kind"] == "CALLS"
    )
