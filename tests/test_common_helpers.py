"""Tests for codegraph.analysis._common helpers."""
from __future__ import annotations

import networkx as nx

from codegraph.analysis._common import _kind_str, in_test_module
from codegraph.graph.schema import EdgeKind, NodeKind

# ---------- _kind_str ----------

def test_kind_str_with_enum_returns_value() -> None:
    assert _kind_str(NodeKind.FUNCTION) == "FUNCTION"


def test_kind_str_with_edge_enum_returns_value() -> None:
    assert _kind_str(EdgeKind.CALLS) == "CALLS"


def test_kind_str_with_string_passthrough() -> None:
    assert _kind_str("FUNCTION") == "FUNCTION"


def test_kind_str_with_none_returns_empty() -> None:
    assert _kind_str(None) == ""


def test_kind_str_with_empty_string_returns_empty() -> None:
    assert _kind_str("") == ""


def test_kind_str_with_zero_returns_empty() -> None:
    # falsy non-string is coerced to "" by `or ""`
    assert _kind_str(0) == ""


# ---------- in_test_module ----------

def test_in_test_module_when_metadata_is_test_true() -> None:
    g: nx.MultiDiGraph = nx.MultiDiGraph()
    g.add_node("n1", metadata={"is_test": True}, file="src/foo.py")
    assert in_test_module(g, "n1") is True


def test_in_test_module_when_no_node_returns_false() -> None:
    g: nx.MultiDiGraph = nx.MultiDiGraph()
    assert in_test_module(g, "missing") is False


def test_in_test_module_path_fallback_tests_subdir() -> None:
    g: nx.MultiDiGraph = nx.MultiDiGraph()
    g.add_node("n1", metadata={}, file="repo/tests/foo.py")
    assert in_test_module(g, "n1") is True


def test_in_test_module_path_fallback_tests_prefix() -> None:
    g: nx.MultiDiGraph = nx.MultiDiGraph()
    g.add_node("n1", metadata={}, file="tests/foo.py")
    assert in_test_module(g, "n1") is True


def test_in_test_module_when_no_file_returns_false() -> None:
    g: nx.MultiDiGraph = nx.MultiDiGraph()
    g.add_node("n1", metadata={})
    assert in_test_module(g, "n1") is False


def test_in_test_module_via_sibling_module_metadata() -> None:
    g: nx.MultiDiGraph = nx.MultiDiGraph()
    # node points to a file; another MODULE node for that same file is_test
    g.add_node(
        "fn", metadata={}, file="src/app/foo.py",
        kind=NodeKind.FUNCTION,
    )
    g.add_node(
        "mod", metadata={"is_test": True}, file="src/app/foo.py",
        kind=NodeKind.MODULE,
    )
    assert in_test_module(g, "fn") is True


def test_in_test_module_non_test_file_false() -> None:
    g: nx.MultiDiGraph = nx.MultiDiGraph()
    g.add_node("n1", metadata={}, file="src/app/foo.py")
    assert in_test_module(g, "n1") is False
