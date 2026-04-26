"""Shared helpers for analysis modules."""
from __future__ import annotations

from collections.abc import Iterable

import networkx as nx

from codegraph.graph.schema import EdgeKind


def _kind_str(value: object) -> str:
    """Return the canonical string form of a NodeKind/EdgeKind/str."""
    return str(getattr(value, "value", value) or "")


REFERENCE_EDGE_KINDS: frozenset[str] = frozenset(
    {
        EdgeKind.CALLS.value,
        EdgeKind.IMPORTS.value,
        EdgeKind.INHERITS.value,
        EdgeKind.IMPLEMENTS.value,
    }
)


def in_test_module(graph: nx.MultiDiGraph, node_id: str) -> bool:
    """True iff the node is in a file whose MODULE node is marked is_test."""
    attrs = graph.nodes.get(node_id) or {}
    metadata = attrs.get("metadata") or {}
    if metadata.get("is_test"):
        return True
    file_path = attrs.get("file")
    if not file_path:
        return False
    # Path-based fallback for non-Python test files (e.g. node --test JS files
    # under tests/) which don't carry the is_test module metadata.
    normalised = str(file_path).replace("\\", "/")
    if "/tests/" in normalised or normalised.startswith("tests/"):
        return True
    for _, other_attrs in graph.nodes(data=True):
        if (
            other_attrs.get("file") == file_path
            and _kind_str(other_attrs.get("kind")) == "MODULE"
            and (other_attrs.get("metadata") or {}).get("is_test")
        ):
            return True
    return False


def filter_kinds(
    graph: nx.MultiDiGraph, allowed: Iterable[str]
) -> nx.MultiDiGraph:
    """Return a subgraph view containing only edges with kinds in ``allowed``."""
    allowed_set = set(allowed)
    out: nx.MultiDiGraph = nx.MultiDiGraph()
    for nid, attrs in graph.nodes(data=True):
        out.add_node(nid, **attrs)
    for src, dst, key, data in graph.edges(keys=True, data=True):
        if data.get("kind") in allowed_set:
            out.add_edge(src, dst, key=key, **data)
    return out
