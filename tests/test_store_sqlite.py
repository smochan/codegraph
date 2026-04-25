"""Tests for SQLiteGraphStore."""
from __future__ import annotations

import random
import string
from pathlib import Path

import pytest

from codegraph.graph.schema import Edge, EdgeKind, Node, NodeKind, make_node_id
from codegraph.graph.store_sqlite import SQLiteGraphStore


def make_random_node(i: int) -> Node:
    qualname = f"mod{i}.Cls{i}"
    file = f"src/mod{i}.py"
    return Node(
        id=make_node_id(NodeKind.CLASS, qualname, file),
        kind=NodeKind.CLASS,
        name=f"Cls{i}",
        qualname=qualname,
        file=file,
        line_start=i,
        line_end=i + 10,
        language="python",
        content_hash="".join(random.choices(string.hexdigits, k=64)),
        metadata={"index": i},
    )


@pytest.fixture
def store(tmp_path: Path) -> SQLiteGraphStore:
    return SQLiteGraphStore(tmp_path / "test.db")


def test_roundtrip_100_nodes_200_edges(store: SQLiteGraphStore) -> None:
    nodes = [make_random_node(i) for i in range(100)]
    store.upsert_nodes(nodes)
    assert store.count_nodes() == 100

    seen: set[tuple[str, str, str]] = set()
    unique_edges: list[Edge] = []
    for i in range(200):
        src_node = nodes[i % 100]
        dst_node = nodes[(i + 1) % 100]
        e = Edge(
            src=src_node.id, dst=dst_node.id, kind=EdgeKind.CALLS,
            file=src_node.file, line=i + 1,
        )
        key = (e.src, e.dst, e.kind.value)
        if key not in seen:
            seen.add(key)
            unique_edges.append(e)
    store.upsert_edges(unique_edges)
    assert store.count_edges() == len(unique_edges)

    node0 = store.get_node(nodes[0].id)
    assert node0 is not None
    assert node0.content_hash == nodes[0].content_hash
    assert node0.metadata == nodes[0].metadata


def test_iter_nodes_by_kind(store: SQLiteGraphStore) -> None:
    nodes = [make_random_node(i) for i in range(10)]
    store.upsert_nodes(nodes)
    result = list(store.iter_nodes(kind=NodeKind.CLASS))
    assert len(result) == 10


def test_iter_nodes_by_file(store: SQLiteGraphStore) -> None:
    nodes = [make_random_node(i) for i in range(10)]
    store.upsert_nodes(nodes)
    result = list(store.iter_nodes(file="src/mod0.py"))
    assert len(result) == 1
    assert result[0].name == "Cls0"


def test_delete_file_cascade(store: SQLiteGraphStore) -> None:
    n1 = make_random_node(1)
    n2 = make_random_node(2)
    store.upsert_nodes([n1, n2])
    edge = Edge(src=n1.id, dst=n2.id, kind=EdgeKind.CALLS)
    store.upsert_edge(edge)
    assert store.count_nodes() == 2
    assert store.count_edges() == 1

    store.delete_file(n1.file)
    assert store.count_nodes() == 1
    assert store.count_edges() == 0


def test_meta(store: SQLiteGraphStore) -> None:
    store.set_meta("key1", "value1")
    assert store.get_meta("key1") == "value1"
    assert store.get_meta("nonexistent") is None


def test_get_node_none(store: SQLiteGraphStore) -> None:
    assert store.get_node("nonexistent") is None
