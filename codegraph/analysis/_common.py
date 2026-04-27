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


EXCLUDED_PATH_FRAGMENTS: tuple[str, ...] = (
    "tests/fixtures/",
    "tests\\fixtures\\",
    "/static/",
    "\\static\\",
)


def is_excluded_path(file_path: str) -> bool:
    """True iff the file path is under a directory excluded from analysis.

    Test fixtures and static frontend assets don't have traceable call graphs
    and should not be analysed for dead-code or untested-symbol detection.
    """
    if not file_path:
        return False
    return any(fragment in file_path for fragment in EXCLUDED_PATH_FRAGMENTS)


def is_protocol_class(graph: nx.MultiDiGraph, class_id: str) -> bool:
    """True iff the class inherits from ``typing.Protocol``.

    Walks INHERITS out-edges and matches any parent whose target name ends in
    ``Protocol``. This covers ``Protocol``, ``typing.Protocol``, and the
    parser's ``unresolved::Protocol`` / ``unresolved::typing.Protocol`` forms.
    """
    for _src, dst, key, data in graph.out_edges(class_id, keys=True, data=True):
        if key != EdgeKind.INHERITS.value:
            continue
        target_name = ""
        meta = data.get("metadata") or {}
        if isinstance(meta, dict):
            target_name = str(meta.get("target_name") or "")
        if not target_name:
            attrs = graph.nodes.get(dst) or {}
            target_name = str(attrs.get("name") or attrs.get("qualname") or dst)
        # Strip an unresolved:: prefix if the dst ID was used as fallback.
        if target_name.startswith("unresolved::"):
            target_name = target_name.split("::", 1)[1]
        # Match bare "Protocol" or any dotted form ending with ".Protocol".
        if target_name == "Protocol" or target_name.endswith(".Protocol"):
            return True
    return False


def in_protocol_class(graph: nx.MultiDiGraph, method_id: str) -> bool:
    """True iff this method's owning class is a typing.Protocol."""
    for _src, dst, key in graph.out_edges(method_id, keys=True):
        if key != EdgeKind.DEFINED_IN.value:
            continue
        attrs = graph.nodes.get(dst) or {}
        if _kind_str(attrs.get("kind")) != "CLASS":
            continue
        if is_protocol_class(graph, dst):
            return True
    return False


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
