"""Risk scoring for diff entries."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

import networkx as nx

from codegraph.analysis.cycles import find_cycles
from codegraph.analysis.hotspots import find_hotspots
from codegraph.graph.schema import EdgeKind
from codegraph.review.differ import EdgeChange, NodeChange


@dataclass
class Risk:
    score: int  # 0-100
    level: str  # low | med | high | critical
    reasons: list[str] = field(default_factory=list)


def _level(score: int) -> str:
    if score >= 81:
        return "critical"
    if score >= 51:
        return "high"
    if score >= 21:
        return "med"
    return "low"


def _kind_str(value: object) -> str:
    return str(getattr(value, "value", value) or "")


def _find_node_id(
    qualname: str, kind: str, graph: nx.MultiDiGraph
) -> str | None:
    for nid, attrs in graph.nodes(data=True):
        if (
            str(attrs.get("qualname") or "") == qualname
            and _kind_str(attrs.get("kind")) == kind
        ):
            return str(nid)
    return None


def _count_callers(node_id: str, graph: nx.MultiDiGraph) -> int:
    count = 0
    for _src, _dst, key in graph.in_edges(node_id, keys=True):
        if key == EdgeKind.CALLS.value:
            count += 1
    return count


def _has_callers_in_new(
    old_node_id: str, old_graph: nx.MultiDiGraph, new_graph: nx.MultiDiGraph
) -> bool:
    """Return True if any caller of ``old_node_id`` (in old) still exists in new."""
    new_ids = set(new_graph.nodes())
    return any(
        src in new_ids
        for src, _dst, _data in old_graph.in_edges(old_node_id, data=True)
    )


def _hotspot_files(graph: nx.MultiDiGraph) -> frozenset[str]:
    return frozenset(h.file for h in find_hotspots(graph, limit=10) if h.file)


def _is_hotspot_file(
    file: str,
    graph: nx.MultiDiGraph,
    cache: dict[str, frozenset[str]] | None = None,
) -> bool:
    if not file:
        return False
    if cache is not None and "files" in cache:
        return file in cache["files"]
    return file in _hotspot_files(graph)


def _is_public_api(qualname: str) -> bool:
    if not qualname:
        return False
    parts = qualname.rsplit(".", 1)
    name = parts[-1]
    return not name.startswith("_")


_SIG_PARAM_RE = re.compile(r"\(([^)]*)\)")


def _param_count(signature: str) -> int:
    if not signature:
        return -1
    m = _SIG_PARAM_RE.search(signature)
    if not m:
        return -1
    inside = m.group(1).strip()
    if not inside:
        return 0
    # Naive split on commas at depth 0 - good enough for python signatures.
    depth = 0
    parts: list[str] = []
    buf: list[str] = []
    for ch in inside:
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
        if ch == "," and depth == 0:
            parts.append("".join(buf).strip())
            buf = []
        else:
            buf.append(ch)
    if buf:
        parts.append("".join(buf).strip())
    return len([p for p in parts if p])


def _param_count_changed(old_sig: str, new_sig: str) -> bool:
    old = _param_count(old_sig)
    new = _param_count(new_sig)
    if old < 0 or new < 0:
        return old_sig != new_sig
    return old != new


def _cycle_total(
    graph: nx.MultiDiGraph,
    cache: dict[str, int] | None = None,
    label: str = "",
) -> int:
    if cache is not None and label in cache:
        return cache[label]
    return find_cycles(graph).total


def _introduces_cycle(
    new_graph: nx.MultiDiGraph,
    old_graph: nx.MultiDiGraph,
    cache: dict[str, int] | None = None,
) -> bool:
    new_total = _cycle_total(new_graph, cache, "new")
    old_total = _cycle_total(old_graph, cache, "old")
    return new_total > old_total


def score_change(
    change: NodeChange | EdgeChange,
    *,
    new_graph: nx.MultiDiGraph,
    old_graph: nx.MultiDiGraph,
    extra: dict[str, Any] | None = None,
) -> Risk:
    """Score a single diff entry against the new + old graphs."""
    score = 0
    reasons: list[str] = []
    extra = extra or {}
    raw_hotspot = extra.get("hotspot_cache")
    hotspot_cache: dict[str, frozenset[str]] | None = (
        raw_hotspot if isinstance(raw_hotspot, dict) else None
    )
    raw_cycle = extra.get("cycle_cache")
    cycle_cache: dict[str, int] | None = (
        raw_cycle if isinstance(raw_cycle, dict) else None
    )

    if isinstance(change, NodeChange):
        new_id = _find_node_id(change.qualname, change.kind, new_graph)
        old_id = _find_node_id(change.qualname, change.kind, old_graph)

        if new_id is not None:
            fan_in = _count_callers(new_id, new_graph)
            if fan_in >= 10:
                score += 40
                reasons.append(f"high blast radius ({fan_in} callers)")

        if (
            change.change_kind == "removed"
            and new_id is None
            and old_id is not None
            and _has_callers_in_new(old_id, old_graph, new_graph)
        ):
            score += 50
            reasons.append("removed symbol still referenced")

        hotspot_graph = (
            old_graph if change.change_kind == "removed" else new_graph
        )
        if _is_hotspot_file(change.file, hotspot_graph, hotspot_cache):
            score += 20
            reasons.append("in hotspot file")

        if change.change_kind == "added" and new_id is not None:
            fan_in = _count_callers(new_id, new_graph)
            if fan_in == 0 and not _is_public_api(change.qualname):
                score += 10
                reasons.append("potentially unreachable")

        if change.change_kind == "modified":
            sig_details = change.details.get("signature") or {}
            old_sig = str(sig_details.get("old") or "")
            new_sig = str(sig_details.get("new") or "")
            if old_sig and new_sig and _param_count_changed(old_sig, new_sig):
                score += 20
                reasons.append("signature change")

    if extra.get("introduces_cycle") or _introduces_cycle(
        new_graph, old_graph, cycle_cache
    ):
        score += 30
        reasons.append("introduces import/call cycle")

    score = min(100, score)
    return Risk(score=score, level=_level(score), reasons=reasons)
