"""Diagram-style visualizations: matrix, treemap, sankey, flowcharts.

These complement the node-link views in ``viz/explore.py`` with views that
actually *tell a story* about the codebase — call volume between modules
(matrix + sankey), file-size landscape (treemap), and call chains for top
entry points (Mermaid flowcharts).

All renderers in this module are pure-Python and produce small JSON blobs
that the dashboard HTML page consumes via D3 / Mermaid loaded from CDN.
"""
from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Any, cast

import networkx as nx

from codegraph.analysis import find_hotspots
from codegraph.viz._style import kind_str

_CALLABLE_KINDS: frozenset[str] = frozenset({"FUNCTION", "METHOD"})


def _is_test_node(attrs: dict[str, Any]) -> bool:
    return bool((attrs.get("metadata") or {}).get("is_test"))

_PACKAGE_RE = re.compile(r"^([^.]+)")


# ----------------------------- module helpers -----------------------------


def _module_index(graph: nx.MultiDiGraph) -> tuple[
    dict[str, str], dict[str, dict[str, Any]]
]:
    """Return (node_id -> module_id, module_id -> info) for every symbol.

    A *module* is a MODULE node. Symbols (CLASS / FUNCTION / METHOD) are
    mapped to the module whose ``file`` matches the symbol's ``file``.
    """
    file_to_module: dict[str, str] = {}
    module_info: dict[str, dict[str, Any]] = {}
    for nid, attrs in graph.nodes(data=True):
        if kind_str(attrs.get("kind")) != "MODULE":
            continue
        f = attrs.get("file")
        if isinstance(f, str):
            file_to_module[f] = nid
        qn = str(attrs.get("qualname") or "")
        match = _PACKAGE_RE.match(qn) if qn else None
        package = match.group(1) if match else ""
        module_info[nid] = {
            "id": nid,
            "qualname": qn,
            "name": attrs.get("name") or qn or nid[:8],
            "file": f or "",
            "package": package,
            "language": str(attrs.get("language") or ""),
            "is_test": bool((attrs.get("metadata") or {}).get("is_test")),
            "loc": 0,
            "symbols": 0,
        }

    node_to_module: dict[str, str] = {}
    for nid, attrs in graph.nodes(data=True):
        kind = kind_str(attrs.get("kind"))
        if kind == "MODULE":
            node_to_module[nid] = nid
            continue
        f = attrs.get("file")
        if isinstance(f, str) and f in file_to_module:
            node_to_module[nid] = file_to_module[f]

    # Approx LOC per module = max line_end of any symbol it contains.
    for nid, attrs in graph.nodes(data=True):
        kind = kind_str(attrs.get("kind"))
        if kind not in ("FUNCTION", "METHOD", "CLASS"):
            continue
        mid = node_to_module.get(nid)
        if mid is None or mid not in module_info:
            continue
        line_end = attrs.get("line_end") or attrs.get("line_start") or 0
        try:
            line_end_int = int(line_end)
        except (TypeError, ValueError):
            line_end_int = 0
        if line_end_int > module_info[mid]["loc"]:
            module_info[mid]["loc"] = line_end_int
        module_info[mid]["symbols"] += 1

    return node_to_module, module_info


# ---------------------------- dependency matrix ---------------------------


@dataclass
class MatrixData:
    modules: list[dict[str, Any]]
    counts: list[list[int]]  # counts[i][j] = calls from modules[i] to modules[j]
    max_count: int


def build_matrix(
    graph: nx.MultiDiGraph, *, top_n: int = 40
) -> MatrixData:
    """Module x Module call-count matrix (cross-module CALLS only)."""
    node_to_module, module_info = _module_index(graph)
    pair_counts: dict[tuple[str, str], int] = defaultdict(int)
    for src, dst, data in graph.edges(data=True):
        if kind_str(data.get("kind")) != "CALLS":
            continue
        sm = node_to_module.get(src)
        dm = node_to_module.get(dst)
        if not sm or not dm or sm == dm:
            continue
        pair_counts[(sm, dm)] += 1

    # Pick the top-N most active modules by total in+out call volume.
    activity: Counter[str] = Counter()
    for (s, d), c in pair_counts.items():
        activity[s] += c
        activity[d] += c
    chosen = [m for m, _ in activity.most_common(top_n)]
    chosen_set = set(chosen)
    chosen.sort(key=lambda m: (module_info[m]["package"], module_info[m]["qualname"]))

    counts = [
        [pair_counts.get((a, b), 0) for b in chosen]
        for a in chosen
    ]
    max_count = max((max(row) for row in counts), default=0)
    return MatrixData(
        modules=[module_info[m] for m in chosen if m in chosen_set],
        counts=counts,
        max_count=max_count,
    )


# --------------------------------- sankey ---------------------------------


def build_sankey(
    graph: nx.MultiDiGraph, *, max_links: int = 60
) -> dict[str, Any]:
    """Sankey-ready data for the heaviest cross-module call flows."""
    node_to_module, module_info = _module_index(graph)
    pair_counts: dict[tuple[str, str], int] = defaultdict(int)
    for src, dst, data in graph.edges(data=True):
        if kind_str(data.get("kind")) != "CALLS":
            continue
        sm = node_to_module.get(src)
        dm = node_to_module.get(dst)
        if not sm or not dm or sm == dm:
            continue
        pair_counts[(sm, dm)] += 1

    top = sorted(pair_counts.items(), key=lambda kv: kv[1], reverse=True)[:max_links]
    used: set[str] = set()
    for (s, d), _c in top:
        used.add(s)
        used.add(d)
    nodes = sorted(used, key=lambda m: module_info[m]["qualname"])
    idx = {m: i for i, m in enumerate(nodes)}
    return {
        "nodes": [
            {
                "name": module_info[m]["name"],
                "qualname": module_info[m]["qualname"],
                "package": module_info[m]["package"],
            }
            for m in nodes
        ],
        "links": [
            {"source": idx[s], "target": idx[d], "value": c}
            for (s, d), c in top
        ],
    }


# ------------------------------- treemap ----------------------------------


def build_treemap(
    graph: nx.MultiDiGraph,
    *,
    hotspot_scores: dict[str, int] | None = None,
) -> dict[str, Any]:
    """Hierarchical {package -> module -> {loc, score}} for D3 treemap."""
    _node_to_module, module_info = _module_index(graph)
    by_package: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for _mid, info in module_info.items():
        if not info["loc"]:
            continue
        score = (hotspot_scores or {}).get(info["file"], 0)
        by_package[info["package"] or "(root)"].append(
            {
                "name": info["qualname"] or info["name"],
                "value": max(info["loc"], 1),
                "symbols": info["symbols"],
                "score": score,
                "file": info["file"],
                "is_test": info["is_test"],
            }
        )

    def _value(item: dict[str, Any]) -> int:
        v = item.get("value", 0)
        return int(v) if isinstance(v, int | float) else 0

    children: list[dict[str, Any]] = []
    for pkg in sorted(by_package):
        items: list[dict[str, Any]] = list(by_package[pkg])
        items.sort(key=lambda x: -_value(x))
        children.append({"name": pkg, "children": items})
    return {"name": "repo", "children": children}


# ---------------------------- flow diagrams -------------------------------


def _trace_outgoing(
    graph: nx.MultiDiGraph,
    start: str,
    *,
    depth: int = 4,
    max_nodes: int = 30,
) -> nx.DiGraph:
    """BFS along CALLS edges from ``start`` up to ``depth`` hops."""
    seen: set[str] = {start}
    frontier: list[tuple[str, int]] = [(start, 0)]
    out: nx.DiGraph = nx.DiGraph()
    out.add_node(start, **dict(graph.nodes[start]))
    while frontier and len(seen) < max_nodes:
        node, d = frontier.pop(0)
        if d >= depth:
            continue
        for _src, dst, data in graph.out_edges(node, data=True):
            if kind_str(data.get("kind")) != "CALLS":
                continue
            if dst not in seen:
                seen.add(dst)
                if dst in graph.nodes:
                    out.add_node(dst, **dict(graph.nodes[dst]))
                frontier.append((dst, d + 1))
            out.add_edge(node, dst)
            if len(seen) >= max_nodes:
                break
    return out


def _mermaid_id(qualname: str, idx: int) -> str:
    safe = re.sub(r"[^a-zA-Z0-9]", "_", qualname)[:40] or "n"
    return f"n{idx}_{safe}"


def _mermaid_label(attrs: dict[str, Any]) -> str:
    name = str(attrs.get("name") or attrs.get("qualname") or "?")
    qn = str(attrs.get("qualname") or "")
    if qn and qn != name:
        # Show last two qualname segments for context.
        parts = qn.split(".")
        name = ".".join(parts[-2:]) if len(parts) > 1 else name
    return name.replace('"', "'")[:48]


def render_flow_diagram(graph: nx.MultiDiGraph, start: str) -> str:
    """Mermaid flowchart of CALLS originating from ``start``."""
    sub = _trace_outgoing(graph, start)
    if sub.number_of_nodes() <= 1:
        return ""
    ids: dict[str, str] = {}
    for i, n in enumerate(sub.nodes()):
        ids[n] = _mermaid_id(str(graph.nodes[n].get("qualname") or n), i)

    lines: list[str] = ["flowchart LR"]
    for n in sub.nodes():
        attrs = dict(graph.nodes[n])
        label = _mermaid_label(attrs)
        kind = kind_str(attrs.get("kind"))
        if kind == "METHOD":
            lines.append(f'    {ids[n]}(["{label}"])')
        elif kind == "CLASS":
            lines.append(f'    {ids[n]}[["{label}"]]')
        elif kind == "MODULE":
            lines.append(f'    {ids[n]}[/"{label}"/]')
        else:
            lines.append(f'    {ids[n]}("{label}")')
    for src, dst in sub.edges():
        lines.append(f"    {ids[src]} --> {ids[dst]}")
    # Highlight the entry node.
    lines.append(f"    style {ids[start]} fill:#6366f1,stroke:#a5b4fc,color:#fff")
    return "\n".join(lines)


def pick_flow_entry_points(
    graph: nx.MultiDiGraph, *, limit: int = 8
) -> list[dict[str, Any]]:
    """Pick interesting flow starting points: top hotspots + high fan-out."""
    candidates: dict[str, dict[str, Any]] = {}

    # 1. Top hotspots (skip tests).
    for h in find_hotspots(graph, limit=limit * 2):
        nid = h.id
        if nid not in graph.nodes:
            continue
        if _is_test_node(dict(graph.nodes[nid])):
            continue
        candidates[nid] = {
            "id": nid,
            "qualname": h.qualname,
            "file": h.file,
            "reason": f"hotspot, fan-in {h.fan_in}",
            "score": h.fan_in * 3 + h.fan_out,
        }

    # 2. High fan-out callables (likely entry points / orchestrators).
    for nid, attrs in graph.nodes(data=True):
        if kind_str(attrs.get("kind")) not in _CALLABLE_KINDS:
            continue
        if _is_test_node(dict(attrs)):
            continue
        out_calls = sum(
            1 for _s, _d, data in graph.out_edges(nid, data=True)
            if kind_str(data.get("kind")) == "CALLS"
        )
        in_calls = sum(
            1 for _s, _d, data in graph.in_edges(nid, data=True)
            if kind_str(data.get("kind")) == "CALLS"
        )
        if out_calls < 3:
            continue
        if nid in candidates:
            candidates[nid]["score"] = max(
                cast(int, candidates[nid]["score"]), out_calls * 2 + in_calls
            )
            continue
        candidates[nid] = {
            "id": nid,
            "qualname": str(attrs.get("qualname") or attrs.get("name") or nid),
            "file": str(attrs.get("file") or ""),
            "reason": f"fan-out {out_calls}",
            "score": out_calls * 2 + in_calls,
        }

    ranked = sorted(
        candidates.values(), key=lambda d: cast(int, d["score"]), reverse=True
    )
    return ranked[:limit]


# ---------------------------- json packaging -----------------------------


def to_json(obj: Any) -> str:
    return json.dumps(obj, separators=(",", ":"), ensure_ascii=False)


__all__ = [
    "MatrixData",
    "build_matrix",
    "build_sankey",
    "build_treemap",
    "pick_flow_entry_points",
    "render_flow_diagram",
    "to_json",
]
