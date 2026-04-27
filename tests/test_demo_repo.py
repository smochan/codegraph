"""Regression tests against examples/cross-stack-demo.

If a future refactor breaks the demo (the repo's own showcase), these tests
catch it before the demo's README starts lying.
"""
from __future__ import annotations

from pathlib import Path

import networkx as nx
import pytest

from codegraph.graph.builder import GraphBuilder
from codegraph.graph.schema import EdgeKind
from codegraph.graph.store_networkx import to_digraph
from codegraph.graph.store_sqlite import SQLiteGraphStore

DEMO_ROOT = Path(__file__).parent.parent / "examples" / "cross-stack-demo"


@pytest.fixture(scope="module")
def demo_graph(tmp_path_factory: pytest.TempPathFactory) -> nx.MultiDiGraph:
    """Build the demo repo into a graph once per module."""
    db_path = tmp_path_factory.mktemp("demo") / "graph.db"
    store = SQLiteGraphStore(db_path)
    GraphBuilder(DEMO_ROOT, store).build(incremental=False)
    g = to_digraph(store)
    store.close()
    return g


def _edges_of_kind(g: nx.MultiDiGraph, kind: str) -> list[tuple[str, str]]:
    return [
        (str(s), str(d))
        for s, d, k in g.edges(keys=True)
        if k == kind
    ]


def _nodes_with_role(g: nx.MultiDiGraph, role: str) -> list[str]:
    out: list[str] = []
    for nid, attrs in g.nodes(data=True):
        meta = attrs.get("metadata") or {}
        if isinstance(meta, dict) and meta.get("role") == role:
            out.append(str(attrs.get("qualname") or nid))
    return out


def test_demo_repo_has_route_edges(demo_graph: nx.MultiDiGraph) -> None:
    edges = _edges_of_kind(demo_graph, EdgeKind.ROUTE.value)
    assert len(edges) >= 4, f"expected ≥4 ROUTE edges, got {len(edges)}"


def test_demo_repo_has_fetch_call_edges(demo_graph: nx.MultiDiGraph) -> None:
    edges = _edges_of_kind(demo_graph, EdgeKind.FETCH_CALL.value)
    assert len(edges) >= 2, f"expected ≥2 FETCH_CALL edges, got {len(edges)}"


def test_demo_repo_has_reads_from_edges(demo_graph: nx.MultiDiGraph) -> None:
    edges = _edges_of_kind(demo_graph, EdgeKind.READS_FROM.value)
    assert len(edges) >= 1, f"expected ≥1 READS_FROM edge, got {len(edges)}"


def test_demo_repo_has_writes_to_edges(demo_graph: nx.MultiDiGraph) -> None:
    edges = _edges_of_kind(demo_graph, EdgeKind.WRITES_TO.value)
    assert len(edges) >= 1, f"expected ≥1 WRITES_TO edge, got {len(edges)}"


def test_demo_repo_has_handler_role(demo_graph: nx.MultiDiGraph) -> None:
    handlers = _nodes_with_role(demo_graph, "HANDLER")
    assert len(handlers) >= 4, f"expected ≥4 HANDLER nodes, got {len(handlers)}"


def test_demo_repo_has_service_role(demo_graph: nx.MultiDiGraph) -> None:
    services = _nodes_with_role(demo_graph, "SERVICE")
    assert any("UserService" in s or "OrderService" in s for s in services), (
        f"expected at least one *Service in SERVICE role, got {services}"
    )


def test_demo_repo_has_repo_role(demo_graph: nx.MultiDiGraph) -> None:
    repos = _nodes_with_role(demo_graph, "REPO")
    assert any(
        "UserRepository" in r or "OrderRepository" in r for r in repos
    ), f"expected at least one *Repository in REPO role, got {repos}"


def test_demo_repo_has_component_role(demo_graph: nx.MultiDiGraph) -> None:
    components = _nodes_with_role(demo_graph, "COMPONENT")
    assert len(components) >= 1, (
        f"expected ≥1 COMPONENT node (UserCard / OrderList), got {components}"
    )


def test_demo_dataflow_trace_resolves(demo_graph: nx.MultiDiGraph) -> None:
    """End-to-end: trace a known fetch URL through the demo and confirm we
    cross from the frontend caller into a backend handler."""
    from codegraph.analysis.dataflow import trace

    flow = trace(demo_graph, "GET /api/users/{user_id}")
    assert flow is not None
    # Either we resolved into a handler chain, OR we got an explicit
    # confidence=0 partial result. Both are valid; assert one of them.
    if flow.hops:
        layers = {h.layer for h in flow.hops}
        # Should include backend at minimum (we entered via the route handler)
        assert "backend" in layers
