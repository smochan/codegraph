"""Tests for NetworkX adapter."""
from __future__ import annotations

from pathlib import Path

import pytest

from codegraph.graph.schema import Edge, EdgeKind, Node, NodeKind, make_node_id
from codegraph.graph.store_networkx import subgraph_around, to_digraph
from codegraph.graph.store_sqlite import SQLiteGraphStore


def make_node(kind: NodeKind, qualname: str, file: str = "f.py") -> Node:
    return Node(
        id=make_node_id(kind, qualname, file),
        kind=kind,
        name=qualname.split(".")[-1],
        qualname=qualname,
        file=file,
        line_start=1,
        line_end=10,
        language="python",
        metadata={},
    )


@pytest.fixture
def store(tmp_path: Path) -> SQLiteGraphStore:
    s = SQLiteGraphStore(tmp_path / "nx_test.db")
    nodes = [
        make_node(NodeKind.FUNCTION, "A"),
        make_node(NodeKind.FUNCTION, "B"),
        make_node(NodeKind.FUNCTION, "C"),
        make_node(NodeKind.FUNCTION, "D"),
        make_node(NodeKind.FUNCTION, "E"),
    ]
    s.upsert_nodes(nodes)
    nid = {n.name: n.id for n in nodes}
    edges = [
        Edge(src=nid["A"], dst=nid["B"], kind=EdgeKind.CALLS),
        Edge(src=nid["B"], dst=nid["C"], kind=EdgeKind.CALLS),
        Edge(src=nid["C"], dst=nid["D"], kind=EdgeKind.CALLS),
    ]
    s.upsert_edges(edges)
    return s


def test_to_digraph(store: SQLiteGraphStore) -> None:
    g = to_digraph(store)
    assert g.number_of_nodes() == 5
    assert g.number_of_edges() == 3


def test_subgraph_depth1(store: SQLiteGraphStore) -> None:
    g = to_digraph(store)
    a_id = next(nid for nid, d in g.nodes(data=True) if d.get("name") == "A")
    sub = subgraph_around(g, a_id, depth=1, direction="out")
    assert sub.number_of_nodes() == 2


def test_subgraph_depth2(store: SQLiteGraphStore) -> None:
    g = to_digraph(store)
    a_id = next(nid for nid, d in g.nodes(data=True) if d.get("name") == "A")
    sub = subgraph_around(g, a_id, depth=2, direction="out")
    assert sub.number_of_nodes() == 3


def test_subgraph_both_direction(store: SQLiteGraphStore) -> None:
    g = to_digraph(store)
    b_id = next(nid for nid, d in g.nodes(data=True) if d.get("name") == "B")
    sub = subgraph_around(g, b_id, depth=1, direction="both")
    assert sub.number_of_nodes() == 3
