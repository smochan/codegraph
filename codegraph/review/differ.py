"""Graph diffing: compare two graphs by (qualname, kind) identity."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import networkx as nx


@dataclass
class NodeChange:
    qualname: str
    kind: str
    file: str
    line_start: int
    signature: str
    change_kind: str  # "added" | "removed" | "modified"
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class EdgeChange:
    src_qualname: str
    dst_qualname: str
    kind: str
    change_kind: str  # "added" | "removed"


@dataclass
class GraphDiff:
    added_nodes: list[NodeChange] = field(default_factory=list)
    removed_nodes: list[NodeChange] = field(default_factory=list)
    modified_nodes: list[NodeChange] = field(default_factory=list)
    added_edges: list[EdgeChange] = field(default_factory=list)
    removed_edges: list[EdgeChange] = field(default_factory=list)

    @property
    def total(self) -> int:
        return (
            len(self.added_nodes)
            + len(self.removed_nodes)
            + len(self.modified_nodes)
            + len(self.added_edges)
            + len(self.removed_edges)
        )


_NodeKey = tuple[str, str]


def _kind_str(value: object) -> str:
    return str(getattr(value, "value", value) or "")


def _node_key(attrs: dict[str, Any]) -> _NodeKey | None:
    qualname = str(attrs.get("qualname") or "")
    kind = _kind_str(attrs.get("kind"))
    if not qualname or not kind:
        return None
    return (qualname, kind)


def _node_payload(attrs: dict[str, Any]) -> dict[str, Any]:
    return {
        "qualname": str(attrs.get("qualname") or ""),
        "kind": _kind_str(attrs.get("kind")),
        "file": str(attrs.get("file") or ""),
        "line_start": int(attrs.get("line_start") or 0),
        "signature": str(attrs.get("signature") or ""),
    }


def _build_node_index(graph: nx.MultiDiGraph) -> dict[_NodeKey, dict[str, Any]]:
    index: dict[_NodeKey, dict[str, Any]] = {}
    for nid, attrs in graph.nodes(data=True):
        key = _node_key(attrs)
        if key is None:
            continue
        # Last write wins - duplicates are exceedingly rare given (qualname, kind, file)
        # identity; we keep the first to be deterministic.
        if key in index:
            continue
        payload = _node_payload(attrs)
        payload["_id"] = nid
        index[key] = payload
    return index


def _id_to_qualname(graph: nx.MultiDiGraph) -> dict[str, str]:
    return {
        nid: str(attrs.get("qualname") or nid)
        for nid, attrs in graph.nodes(data=True)
    }


def _edge_keys(
    graph: nx.MultiDiGraph, id_map: dict[str, str]
) -> set[tuple[str, str, str]]:
    keys: set[tuple[str, str, str]] = set()
    for src, dst, data in graph.edges(data=True):
        kind = _kind_str(data.get("kind"))
        src_qn = id_map.get(src, src)
        dst_qn = id_map.get(dst, dst)
        keys.add((src_qn, dst_qn, kind))
    return keys


def diff_graphs(old: nx.MultiDiGraph, new: nx.MultiDiGraph) -> GraphDiff:
    """Diff two graphs by ``(qualname, kind)`` node identity.

    A node is *modified* when the same identity exists in both graphs but
    its ``file`` or ``signature`` changed.

    ``line_start`` is intentionally NOT a modification trigger: when a PR
    edits the top of a file, every symbol below the edit shifts down by N
    lines and would otherwise show up as "modified" even though their
    actual signatures are identical. Pure line-shift noise was producing
    50+ false-positive ``modified-signature`` findings on PRs that touched
    high-traffic files (``app.js``, ``typescript.py``).

    The ``line_start`` value is still captured on each ``NodeChange`` for
    rendering — it just no longer triggers the change.
    """
    diff = GraphDiff()

    old_idx = _build_node_index(old)
    new_idx = _build_node_index(new)

    for key, new_payload in new_idx.items():
        if key not in old_idx:
            diff.added_nodes.append(
                NodeChange(
                    qualname=new_payload["qualname"],
                    kind=new_payload["kind"],
                    file=new_payload["file"],
                    line_start=new_payload["line_start"],
                    signature=new_payload["signature"],
                    change_kind="added",
                )
            )
            continue
        old_payload = old_idx[key]
        details: dict[str, Any] = {}
        for field_name in ("file", "signature"):
            if old_payload[field_name] != new_payload[field_name]:
                details[field_name] = {
                    "old": old_payload[field_name],
                    "new": new_payload[field_name],
                }
        # Record line drift in details for diagnostic output, but DON'T let
        # it alone trigger "modified".
        if (
            old_payload["line_start"] != new_payload["line_start"]
            and details
        ):
            details["line_start"] = {
                "old": old_payload["line_start"],
                "new": new_payload["line_start"],
            }
        if details:
            diff.modified_nodes.append(
                NodeChange(
                    qualname=new_payload["qualname"],
                    kind=new_payload["kind"],
                    file=new_payload["file"],
                    line_start=new_payload["line_start"],
                    signature=new_payload["signature"],
                    change_kind="modified",
                    details=details,
                )
            )

    for key, old_payload in old_idx.items():
        if key in new_idx:
            continue
        diff.removed_nodes.append(
            NodeChange(
                qualname=old_payload["qualname"],
                kind=old_payload["kind"],
                file=old_payload["file"],
                line_start=old_payload["line_start"],
                signature=old_payload["signature"],
                change_kind="removed",
            )
        )

    old_id_map = _id_to_qualname(old)
    new_id_map = _id_to_qualname(new)
    old_edges = _edge_keys(old, old_id_map)
    new_edges = _edge_keys(new, new_id_map)

    for src_qn, dst_qn, kind in sorted(new_edges - old_edges):
        diff.added_edges.append(
            EdgeChange(
                src_qualname=src_qn,
                dst_qualname=dst_qn,
                kind=kind,
                change_kind="added",
            )
        )
    for src_qn, dst_qn, kind in sorted(old_edges - new_edges):
        diff.removed_edges.append(
            EdgeChange(
                src_qualname=src_qn,
                dst_qualname=dst_qn,
                kind=kind,
                change_kind="removed",
            )
        )

    return diff
