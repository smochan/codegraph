"""Tests for graph schema."""
from __future__ import annotations

from codegraph.graph.schema import Edge, EdgeKind, Node, NodeKind, make_node_id


def test_make_node_id_stable() -> None:
    id1 = make_node_id(NodeKind.FUNCTION, "foo.bar", "src/foo.py")
    id2 = make_node_id(NodeKind.FUNCTION, "foo.bar", "src/foo.py")
    assert id1 == id2
    assert len(id1) == 32


def test_make_node_id_different_inputs() -> None:
    id1 = make_node_id(NodeKind.FUNCTION, "foo.bar", "src/foo.py")
    id2 = make_node_id(NodeKind.CLASS, "foo.bar", "src/foo.py")
    id3 = make_node_id(NodeKind.FUNCTION, "foo.baz", "src/foo.py")
    id4 = make_node_id(NodeKind.FUNCTION, "foo.bar", "src/bar.py")
    assert id1 != id2
    assert id1 != id3
    assert id1 != id4


def test_node_json_roundtrip() -> None:
    node = Node(
        id=make_node_id(NodeKind.CLASS, "mymod.MyClass", "mymod.py"),
        kind=NodeKind.CLASS,
        name="MyClass",
        qualname="mymod.MyClass",
        file="mymod.py",
        line_start=10,
        line_end=30,
        signature="class MyClass(Base)",
        docstring="A class.",
        content_hash="abc123",
        language="python",
        metadata={"x": 1},
    )
    j = node.model_dump_json()
    node2 = Node.model_validate_json(j)
    assert node2 == node


def test_edge_json_roundtrip() -> None:
    edge = Edge(
        src="aaa", dst="bbb", kind=EdgeKind.CALLS,
        file="src/x.py", line=42,
        metadata={"target_name": "foo"},
    )
    j = edge.model_dump_json()
    edge2 = Edge.model_validate_json(j)
    assert edge2 == edge


def test_all_node_kinds() -> None:
    for k in NodeKind:
        assert k.value


def test_all_edge_kinds() -> None:
    for k in EdgeKind:
        assert k.value
