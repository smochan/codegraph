"""Tests for cycle qualname resolution in find_cycles + report rendering."""
from __future__ import annotations

import networkx as nx

from codegraph.analysis.cycles import Cycle, CycleReport, find_cycles
from codegraph.analysis.metrics import GraphMetrics
from codegraph.analysis.report import AnalyzeReport, report_to_markdown
from codegraph.graph.schema import EdgeKind


def _make_call_cycle_graph() -> nx.MultiDiGraph:
    """Build a tiny graph with a 3-node call cycle a -> b -> c -> a."""
    g: nx.MultiDiGraph = nx.MultiDiGraph()
    g.add_node("id_a", qualname="pkg.mod.a", name="a", kind="FUNCTION")
    g.add_node("id_b", qualname="pkg.mod.b", name="b", kind="FUNCTION")
    g.add_node("id_c", qualname="pkg.mod.c", name="c", kind="FUNCTION")
    g.add_edge("id_a", "id_b", kind=EdgeKind.CALLS.value)
    g.add_edge("id_b", "id_c", kind=EdgeKind.CALLS.value)
    g.add_edge("id_c", "id_a", kind=EdgeKind.CALLS.value)
    return g


def test_find_cycles_attaches_qualnames() -> None:
    g = _make_call_cycle_graph()
    rep = find_cycles(g)
    assert len(rep.call_cycles) == 1
    cyc = rep.call_cycles[0]
    assert isinstance(cyc, Cycle)
    assert sorted(cyc.node_ids) == ["id_a", "id_b", "id_c"]
    assert sorted(cyc.qualnames) == ["pkg.mod.a", "pkg.mod.b", "pkg.mod.c"]
    # Order parity: qualnames[i] corresponds to node_ids[i].
    assert len(cyc.node_ids) == len(cyc.qualnames)


def test_find_cycles_falls_back_to_id_when_qualname_missing() -> None:
    g: nx.MultiDiGraph = nx.MultiDiGraph()
    # Self-loop, no qualname/name -> should fall back to node id.
    g.add_node("loner", kind="FUNCTION")
    g.add_edge("loner", "loner", kind=EdgeKind.CALLS.value)
    rep = find_cycles(g)
    assert len(rep.call_cycles) == 1
    cyc = rep.call_cycles[0]
    assert cyc.node_ids == ["loner"]
    assert cyc.qualnames == ["loner"]


def test_report_markdown_renders_qualnames_not_hashes() -> None:
    g = _make_call_cycle_graph()
    rep = find_cycles(g)
    metrics = GraphMetrics(
        total_nodes=3,
        total_edges=3,
        nodes_by_kind={"FUNCTION": 3},
        edges_by_kind={"CALLS": 3},
        languages={},
        top_files_by_nodes=[],
        unresolved_edges=0,
    )
    full = AnalyzeReport(
        metrics=metrics,
        cycles=rep,
        dead_code=[],
        untested=[],
        hotspots=[],
    )
    md = report_to_markdown(full)
    assert "Call cycles (1)" in md
    assert "pkg.mod.a" in md
    assert "pkg.mod.b" in md
    assert "pkg.mod.c" in md
    # Hash-like opaque ids should NOT appear in the cycles section.
    assert "id_a" not in md
    assert "id_b" not in md


def test_report_markdown_no_cycle_section_when_empty() -> None:
    metrics = GraphMetrics(
        total_nodes=0,
        total_edges=0,
        nodes_by_kind={},
        edges_by_kind={},
        languages={},
        top_files_by_nodes=[],
        unresolved_edges=0,
    )
    full = AnalyzeReport(
        metrics=metrics,
        cycles=CycleReport(),
        dead_code=[],
        untested=[],
        hotspots=[],
    )
    md = report_to_markdown(full)
    assert "## Cycles" in md
    assert "_None._" in md
    assert "Call cycles" not in md
    assert "Import cycles" not in md


def test_to_dict_includes_node_ids_and_qualnames() -> None:
    g = _make_call_cycle_graph()
    rep = find_cycles(g)
    metrics = GraphMetrics(
        total_nodes=3,
        total_edges=3,
        nodes_by_kind={},
        edges_by_kind={},
        languages={},
        top_files_by_nodes=[],
        unresolved_edges=0,
    )
    full = AnalyzeReport(
        metrics=metrics, cycles=rep, dead_code=[], untested=[], hotspots=[]
    )
    payload = full.to_dict()
    call_cycles = payload["cycles"]["call_cycles"]
    assert len(call_cycles) == 1
    entry = call_cycles[0]
    assert set(entry.keys()) == {"node_ids", "qualnames"}
    assert sorted(entry["node_ids"]) == ["id_a", "id_b", "id_c"]
    assert sorted(entry["qualnames"]) == ["pkg.mod.a", "pkg.mod.b", "pkg.mod.c"]


def test_mcp_tool_cycles_includes_qualnames() -> None:
    from codegraph.mcp_server.server import tool_cycles

    g = _make_call_cycle_graph()
    result = tool_cycles(g)
    assert result["total"] == 1
    assert len(result["call_cycles"]) == 1
    entry = result["call_cycles"][0]
    assert "node_ids" in entry
    assert "qualnames" in entry
    assert sorted(entry["qualnames"]) == ["pkg.mod.a", "pkg.mod.b", "pkg.mod.c"]
