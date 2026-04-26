"""Tests for codegraph.mcp_server.server._resolve_node."""
from __future__ import annotations

import networkx as nx

from codegraph.mcp_server.server import _resolve_node


def test_resolve_node_exact_id_match() -> None:
    g: nx.MultiDiGraph = nx.MultiDiGraph()
    g.add_node("pkg.mod.fn", qualname="pkg.mod.fn")
    assert _resolve_node(g, "pkg.mod.fn") == "pkg.mod.fn"


def test_resolve_node_by_qualname_attribute() -> None:
    g: nx.MultiDiGraph = nx.MultiDiGraph()
    g.add_node("nid-1", qualname="pkg.mod.fn")
    assert _resolve_node(g, "pkg.mod.fn") == "nid-1"


def test_resolve_node_case_insensitive_qualname() -> None:
    g: nx.MultiDiGraph = nx.MultiDiGraph()
    g.add_node("nid-1", qualname="Pkg.Mod.Fn")
    assert _resolve_node(g, "pkg.mod.fn") == "nid-1"


def test_resolve_node_returns_none_when_missing() -> None:
    g: nx.MultiDiGraph = nx.MultiDiGraph()
    g.add_node("nid-1", qualname="other")
    assert _resolve_node(g, "missing.qn") is None


def test_resolve_node_empty_graph() -> None:
    g: nx.MultiDiGraph = nx.MultiDiGraph()
    assert _resolve_node(g, "anything") is None


def test_resolve_node_handles_node_without_qualname() -> None:
    g: nx.MultiDiGraph = nx.MultiDiGraph()
    g.add_node("nid-1")  # no qualname attr
    assert _resolve_node(g, "anything") is None
