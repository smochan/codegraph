"""Aggregate analyze + symbol-resolution helpers used by the CLI."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Any

import networkx as nx

from codegraph.analysis import (
    BlastRadiusResult,
    CycleReport,
    DeadNode,
    GraphMetrics,
    Hotspot,
    UntestedNode,
    blast_radius,
    compute_metrics,
    find_cycles,
    find_dead_code,
    find_hotspots,
    find_untested,
)
from codegraph.graph.schema import NodeKind


@dataclass
class AnalyzeReport:
    metrics: GraphMetrics
    cycles: CycleReport
    dead_code: list[DeadNode]
    untested: list[UntestedNode]
    hotspots: list[Hotspot]
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "metrics": _metrics_to_dict(self.metrics),
            "cycles": {
                "import_cycles": self.cycles.import_cycles,
                "call_cycles": self.cycles.call_cycles,
                "total": self.cycles.total,
            },
            "dead_code": [asdict(d) for d in self.dead_code],
            "untested": [asdict(u) for u in self.untested],
            "hotspots": [asdict(h) for h in self.hotspots],
            "warnings": list(self.warnings),
        }


def _metrics_to_dict(m: GraphMetrics) -> dict[str, Any]:
    return {
        "total_nodes": m.total_nodes,
        "total_edges": m.total_edges,
        "nodes_by_kind": dict(m.nodes_by_kind),
        "edges_by_kind": dict(m.edges_by_kind),
        "languages": dict(m.languages),
        "top_files_by_nodes": [list(t) for t in m.top_files_by_nodes],
        "unresolved_edges": m.unresolved_edges,
    }


def run_full_analyze(
    graph: nx.MultiDiGraph, *, hotspot_limit: int = 20
) -> AnalyzeReport:
    return AnalyzeReport(
        metrics=compute_metrics(graph),
        cycles=find_cycles(graph),
        dead_code=find_dead_code(graph),
        untested=find_untested(graph),
        hotspots=find_hotspots(graph, limit=hotspot_limit),
    )


def report_to_json(report: AnalyzeReport) -> str:
    return json.dumps(report.to_dict(), indent=2, sort_keys=True)


def report_to_markdown(report: AnalyzeReport) -> str:
    m = report.metrics
    lines: list[str] = ["# codegraph analysis", ""]
    lines.append("## Metrics")
    lines.append("")
    lines.append(f"- Nodes: **{m.total_nodes}**")
    lines.append(f"- Edges: **{m.total_edges}**")
    lines.append(f"- Unresolved edges: **{m.unresolved_edges}**")
    if m.nodes_by_kind:
        lines.append("- Nodes by kind: " + ", ".join(
            f"{k}={v}" for k, v in m.nodes_by_kind.items()
        ))
    if m.edges_by_kind:
        lines.append("- Edges by kind: " + ", ".join(
            f"{k}={v}" for k, v in m.edges_by_kind.items()
        ))
    if m.languages:
        lines.append("- Languages: " + ", ".join(
            f"{k}={v}" for k, v in m.languages.items()
        ))
    if m.top_files_by_nodes:
        lines.append("")
        lines.append("### Top files by node count")
        lines.append("")
        for path, count in m.top_files_by_nodes:
            lines.append(f"- `{path}` — {count} nodes")

    lines.append("")
    lines.append("## Cycles")
    lines.append("")
    if not report.cycles.total:
        lines.append("_None._")
    else:
        if report.cycles.import_cycles:
            lines.append(f"### Import cycles ({len(report.cycles.import_cycles)})")
            for cyc in report.cycles.import_cycles[:10]:
                lines.append("- " + " → ".join(cyc))
        if report.cycles.call_cycles:
            lines.append(f"### Call cycles ({len(report.cycles.call_cycles)})")
            for cyc in report.cycles.call_cycles[:10]:
                lines.append("- " + " → ".join(cyc))

    lines.append("")
    lines.append(f"## Dead code ({len(report.dead_code)})")
    lines.append("")
    if not report.dead_code:
        lines.append("_None._")
    else:
        for node in report.dead_code[:50]:
            lines.append(
                f"- `{node.qualname}` ({node.kind.lower()}) — "
                f"{node.file}:{node.line_start}"
            )
        if len(report.dead_code) > 50:
            lines.append(f"- … and {len(report.dead_code) - 50} more")

    lines.append("")
    lines.append(f"## Untested functions ({len(report.untested)})")
    lines.append("")
    if not report.untested:
        lines.append("_None — every function has at least one test caller._")
    else:
        for u in report.untested[:50]:
            lines.append(
                f"- `{u.qualname}` ({u.kind.lower()}) — "
                f"{u.file}:{u.line_start} (callers: {u.incoming_calls})"
            )
        if len(report.untested) > 50:
            lines.append(f"- … and {len(report.untested) - 50} more")

    lines.append("")
    lines.append(f"## Hotspots (top {len(report.hotspots)})")
    lines.append("")
    if not report.hotspots:
        lines.append("_None._")
    else:
        lines.append("| Symbol | File | Fan-in | Fan-out | LOC |")
        lines.append("|---|---|---:|---:|---:|")
        for h in report.hotspots:
            lines.append(
                f"| `{h.qualname}` | {h.file} | {h.fan_in} | "
                f"{h.fan_out} | {h.loc} |"
            )

    return "\n".join(lines).rstrip() + "\n"


def find_symbol(graph: nx.MultiDiGraph, symbol: str) -> str | None:
    """Resolve a CLI symbol string to a node id. Tries qualname, then name,
    then file path, then unique substring match. Prefers callable kinds."""
    callable_kinds = {NodeKind.FUNCTION.value, NodeKind.METHOD.value}
    by_qualname: list[tuple[str, str]] = []
    by_name: list[tuple[str, str]] = []
    by_file: list[tuple[str, str]] = []
    for nid, attrs in graph.nodes(data=True):
        kind = str(attrs.get("kind") or "")
        qn = str(attrs.get("qualname") or "")
        name = str(attrs.get("name") or "")
        file_path = str(attrs.get("file") or "")
        if qn == symbol:
            by_qualname.append((nid, kind))
        if name == symbol:
            by_name.append((nid, kind))
        if file_path == symbol:
            by_file.append((nid, kind))

    for bucket in (by_qualname, by_name, by_file):
        if not bucket:
            continue
        prefer = [nid for nid, kind in bucket if kind in callable_kinds]
        if prefer:
            return prefer[0]
        return bucket[0][0]

    # substring match across qualnames
    candidates: list[tuple[str, str]] = []
    for nid, attrs in graph.nodes(data=True):
        qn = str(attrs.get("qualname") or "")
        if symbol in qn:
            candidates.append((nid, str(attrs.get("kind") or "")))
    if len(candidates) == 1:
        return candidates[0][0]
    prefer = [nid for nid, kind in candidates if kind in callable_kinds]
    if len(prefer) == 1:
        return prefer[0]
    return None


__all__ = [
    "AnalyzeReport",
    "BlastRadiusResult",
    "blast_radius",
    "find_symbol",
    "report_to_json",
    "report_to_markdown",
    "run_full_analyze",
]
