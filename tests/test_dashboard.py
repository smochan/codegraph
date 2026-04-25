"""Tests for diagram + dashboard renderers."""
from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

import networkx as nx
import pytest

from codegraph.graph.builder import GraphBuilder
from codegraph.graph.store_networkx import to_digraph
from codegraph.graph.store_sqlite import SQLiteGraphStore
from codegraph.viz.dashboard import render_dashboard
from codegraph.viz.diagrams import (
    build_matrix,
    build_sankey,
    build_treemap,
    pick_flow_entry_points,
    render_flow_diagram,
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


def test_build_matrix_counts_only_cross_module_calls(
    graph: nx.MultiDiGraph,
) -> None:
    m = build_matrix(graph, top_n=20)
    n = len(m.modules)
    assert n > 0
    assert len(m.counts) == n
    assert all(len(row) == n for row in m.counts)
    # Diagonal must be 0 (no self-loops counted).
    assert all(m.counts[i][i] == 0 for i in range(n))


def test_build_sankey_returns_links(graph: nx.MultiDiGraph) -> None:
    s = build_sankey(graph, max_links=20)
    assert {"nodes", "links"} <= set(s.keys())
    for link in s["links"]:
        assert link["source"] != link["target"]
        assert link["value"] >= 1


def test_build_treemap_groups_by_package(graph: nx.MultiDiGraph) -> None:
    tm = build_treemap(graph)
    assert tm["name"] == "repo"
    assert tm["children"], "expected at least one package"
    leaf = tm["children"][0]["children"][0]
    assert leaf["value"] >= 1
    assert "file" in leaf


def test_render_flow_diagram_produces_mermaid(graph: nx.MultiDiGraph) -> None:
    entries = pick_flow_entry_points(graph, limit=5)
    if not entries:
        pytest.skip("fixture has no callable entry points with downstream calls")
    diagram = render_flow_diagram(graph, entries[0]["id"])
    assert diagram.startswith("flowchart LR")
    assert "-->" in diagram
    assert "style " in diagram  # entry-point highlight


def test_render_dashboard_embeds_payload(
    graph: nx.MultiDiGraph, tmp_path: Path
) -> None:
    out = tmp_path / "dash.html"
    render_dashboard(graph, out, matrix_top_n=10, sankey_links=10, flow_count=3)
    text = out.read_text(encoding="utf-8")

    # Tabs are present.
    for label in ("Overview", "Architecture", "Flows", "Matrix", "Sankey", "Treemap"):
        assert label in text, f"missing tab {label}"

    # External libs are referenced (CDN).
    assert "d3.v7.min.js" in text
    assert "mermaid" in text
    assert "d3-sankey" in text

    # Embedded payload parses as JSON and has all expected sections.
    match = re.search(r"const DATA = (\{.+?\});\s*const TABS", text, re.S)
    assert match, "embedded DATA payload missing"
    data = json.loads(match.group(1))
    assert {
        "metrics",
        "issues",
        "hotspots",
        "matrix",
        "sankey",
        "treemap",
        "flows",
        "files",
    } <= set(data.keys())
    assert data["metrics"]["nodes"] > 0
