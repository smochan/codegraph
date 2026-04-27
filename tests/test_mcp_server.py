"""Tests for the MCP server tool handlers."""
from __future__ import annotations

import shutil
from pathlib import Path

import networkx as nx
import pytest

from codegraph.graph.builder import GraphBuilder
from codegraph.graph.store_networkx import to_digraph
from codegraph.graph.store_sqlite import SQLiteGraphStore

FIXTURES = Path(__file__).parent / "fixtures"

EXPECTED_TOOLS = {
    "find_symbol",
    "callers",
    "callees",
    "blast_radius",
    "subgraph",
    "dead_code",
    "cycles",
    "untested",
    "hotspots",
    "metrics",
    "dataflow_routes",
}


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


# ---------------------------------------------------------------------------
# Tool-registry smoke test
# ---------------------------------------------------------------------------

def test_list_tools() -> None:
    from codegraph.mcp_server.server import tool_registry

    registered = set(tool_registry.keys())
    assert registered == EXPECTED_TOOLS, f"Mismatch: {registered ^ EXPECTED_TOOLS}"


# ---------------------------------------------------------------------------
# Individual tool tests
# ---------------------------------------------------------------------------

def test_find_symbol_returns_matches(fixture_graph: nx.MultiDiGraph) -> None:
    from codegraph.mcp_server.server import tool_find_symbol

    results = tool_find_symbol(fixture_graph, query="Dog")
    assert len(results) > 0
    qualnames = [r["qualname"] for r in results]
    assert any("Dog" in qn for qn in qualnames)

    # Check result shape
    first = results[0]
    assert "qualname" in first
    assert "kind" in first
    assert "file" in first
    assert "line" in first


def test_find_symbol_kind_filter(fixture_graph: nx.MultiDiGraph) -> None:
    from codegraph.mcp_server.server import tool_find_symbol

    results_class = tool_find_symbol(fixture_graph, query="Animal", kind="class")
    assert all(r["kind"].lower() == "class" for r in results_class)


def test_find_symbol_limit(fixture_graph: nx.MultiDiGraph) -> None:
    from codegraph.mcp_server.server import tool_find_symbol

    results = tool_find_symbol(fixture_graph, query="", limit=2)
    assert len(results) <= 2


def test_callers_basic(fixture_graph: nx.MultiDiGraph) -> None:
    from codegraph.mcp_server.server import tool_callers

    # Find a node to query — use any function or method that exists
    fn_nodes = [
        nid for nid, attrs in fixture_graph.nodes(data=True)
        if "function" in str(attrs.get("kind") or "").lower()
        or "method" in str(attrs.get("kind") or "").lower()
    ]
    if not fn_nodes:
        pytest.skip("no function nodes in fixture graph")

    nid = fn_nodes[0]
    attrs = fixture_graph.nodes[nid]
    qualname = str(attrs.get("qualname") or nid)

    results = tool_callers(fixture_graph, qualname=qualname, depth=1)
    # May be empty if nothing calls it — just verify shape
    for r in results:
        assert "qualname" in r
        assert "file" in r
        assert "depth" in r


def test_callers_nonexistent_returns_empty(fixture_graph: nx.MultiDiGraph) -> None:
    from codegraph.mcp_server.server import tool_callers

    results = tool_callers(fixture_graph, qualname="nonexistent.does.not.exist")
    assert results == []


def test_callees_basic(fixture_graph: nx.MultiDiGraph) -> None:
    from codegraph.mcp_server.server import tool_callees

    fn_nodes = [
        nid for nid, attrs in fixture_graph.nodes(data=True)
        if "function" in str(attrs.get("kind") or "").lower()
        or "method" in str(attrs.get("kind") or "").lower()
    ]
    if not fn_nodes:
        pytest.skip("no function nodes in fixture graph")

    nid = fn_nodes[0]
    attrs = fixture_graph.nodes[nid]
    qualname = str(attrs.get("qualname") or nid)

    results = tool_callees(fixture_graph, qualname=qualname, depth=1)
    for r in results:
        assert "qualname" in r
        assert "file" in r
        assert "depth" in r


def test_subgraph_returns_nodes_and_edges(fixture_graph: nx.MultiDiGraph) -> None:
    from codegraph.mcp_server.server import tool_subgraph

    class_nodes = [
        nid for nid, attrs in fixture_graph.nodes(data=True)
        if "class" in str(attrs.get("kind") or "").lower()
    ]
    if not class_nodes:
        pytest.skip("no class nodes in fixture graph")

    nid = class_nodes[0]
    attrs = fixture_graph.nodes[nid]
    qualname = str(attrs.get("qualname") or nid)

    result = tool_subgraph(fixture_graph, qualnames=[qualname], depth=1)
    assert "nodes" in result
    assert "edges" in result
    assert isinstance(result["nodes"], list)
    assert isinstance(result["edges"], list)
    # At minimum the seed node itself should be in the subgraph
    qnames = [n["qualname"] for n in result["nodes"]]
    assert any(qualname in qn for qn in qnames)


def test_blast_radius_wraps_analysis(fixture_graph: nx.MultiDiGraph) -> None:
    from codegraph.mcp_server.server import tool_blast_radius

    fn_nodes = [
        nid for nid, attrs in fixture_graph.nodes(data=True)
        if "function" in str(attrs.get("kind") or "").lower()
        or "method" in str(attrs.get("kind") or "").lower()
    ]
    if not fn_nodes:
        pytest.skip("no function nodes in fixture graph")

    nid = fn_nodes[0]
    attrs = fixture_graph.nodes[nid]
    qualname = str(attrs.get("qualname") or nid)

    result = tool_blast_radius(fixture_graph, qualname=qualname, depth=2)
    assert "target" in result
    assert "size" in result
    assert "nodes" in result
    assert "files" in result
    assert isinstance(result["nodes"], list)


def test_dead_code_returns_list(fixture_graph: nx.MultiDiGraph) -> None:
    from codegraph.mcp_server.server import tool_dead_code

    results = tool_dead_code(fixture_graph, limit=50)
    assert isinstance(results, list)
    for r in results:
        assert "qualname" in r
        assert "kind" in r
        assert "file" in r
        assert "reason" in r


def test_cycles_returns_report(fixture_graph: nx.MultiDiGraph) -> None:
    from codegraph.mcp_server.server import tool_cycles

    result = tool_cycles(fixture_graph)
    assert "import_cycles" in result
    assert "call_cycles" in result
    assert "total" in result


def test_untested_returns_list(fixture_graph: nx.MultiDiGraph) -> None:
    from codegraph.mcp_server.server import tool_untested

    results = tool_untested(fixture_graph, limit=50)
    assert isinstance(results, list)
    for r in results:
        assert "qualname" in r
        assert "kind" in r


def test_hotspots_returns_list(fixture_graph: nx.MultiDiGraph) -> None:
    from codegraph.mcp_server.server import tool_hotspots

    results = tool_hotspots(fixture_graph, limit=20)
    assert isinstance(results, list)
    for r in results:
        assert "qualname" in r
        assert "fan_in" in r
        assert "fan_out" in r


def test_metrics_returns_counts(fixture_graph: nx.MultiDiGraph) -> None:
    from codegraph.mcp_server.server import tool_metrics

    result = tool_metrics(fixture_graph)
    assert "total_nodes" in result
    assert "total_edges" in result
    assert "nodes_by_kind" in result
    assert result["total_nodes"] > 0
