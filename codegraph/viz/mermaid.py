"""Mermaid renderer with file-clustering and per-kind coloring."""
from __future__ import annotations

import re
from collections import defaultdict

import networkx as nx

from codegraph.viz._style import EDGE_STYLE, KIND_CLASS, kind_str

_SAFE_RE = re.compile(r"[^a-zA-Z0-9_]+")


def _safe_id(node_id: str, prefix: str = "n_") -> str:
    return prefix + _SAFE_RE.sub("_", node_id)[:32]


def _safe_subgraph_id(name: str) -> str:
    return "g_" + _SAFE_RE.sub("_", name)[:48]


def _label(attrs: dict[str, object]) -> str:
    raw = str(attrs.get("name") or "")
    if not raw:
        raw = str(attrs.get("qualname") or "?")
    return raw.replace('"', "'").replace("[", "(").replace("]", ")")


def render_mermaid(
    graph: nx.MultiDiGraph,
    *,
    cluster_by_file: bool = True,
    show_legend: bool = True,
) -> str:
    """Return a Mermaid ``flowchart LR`` diagram of ``graph``.

    Nodes are colored by NodeKind; edges by EdgeKind. When
    ``cluster_by_file`` is True, nodes that share a file path are grouped
    into a Mermaid subgraph.
    """
    lines: list[str] = ["flowchart LR"]

    classes = {
        "file": "stroke:#475569,fill:#e2e8f0,color:#1e293b",
        "module": "stroke:#3730a3,fill:#e0e7ff,color:#1e1b4b",
        "klass": "stroke:#b45309,fill:#fef3c7,color:#451a03",
        "func": "stroke:#047857,fill:#d1fae5,color:#022c22",
        "method": "stroke:#15803d,fill:#dcfce7,color:#052e16",
        "var": "stroke:#4b5563,fill:#f3f4f6,color:#111827",
        "param": "stroke:#6b7280,fill:#f9fafb,color:#111827",
        "imp": "stroke:#0369a1,fill:#e0f2fe,color:#082f49",
        "test": "stroke:#be185d,fill:#fce7f3,color:#500724",
    }
    for cls, style in classes.items():
        lines.append(f"    classDef {cls} {style};")

    by_file: dict[str, list[tuple[str, dict[str, object]]]] = defaultdict(list)
    free: list[tuple[str, dict[str, object]]] = []
    for nid, attrs in graph.nodes(data=True):
        file_path = attrs.get("file")
        if cluster_by_file and isinstance(file_path, str) and file_path:
            by_file[file_path].append((nid, attrs))
        else:
            free.append((nid, attrs))

    safe_map: dict[str, str] = {}

    def _emit_node(nid: str, attrs: dict[str, object], indent: str) -> None:
        sid = _safe_id(nid)
        safe_map[nid] = sid
        kind = kind_str(attrs.get("kind"))
        cls = KIND_CLASS.get(kind, "var")
        label = f"{kind}: {_label(attrs)}"
        lines.append(f'{indent}{sid}["{label}"]:::{cls}')

    for file_path, members in sorted(by_file.items()):
        sg_id = _safe_subgraph_id(file_path)
        lines.append(f'    subgraph {sg_id}["{file_path}"]')
        for nid, attrs in members:
            _emit_node(nid, attrs, "        ")
        lines.append("    end")
    for nid, attrs in free:
        _emit_node(nid, attrs, "    ")

    seen: set[tuple[str, str, str]] = set()
    for src, dst, data in graph.edges(data=True):
        if src not in safe_map or dst not in safe_map:
            continue
        ek = kind_str(data.get("kind"))
        key = (src, dst, ek)
        if key in seen:
            continue
        seen.add(key)
        style = EDGE_STYLE.get(ek, "solid")
        arrow = "-->" if style != "dotted" else "-.->"
        if style == "bold":
            arrow = "==>"
        lines.append(
            f"    {safe_map[src]} {arrow}|{ek}| {safe_map[dst]}"
        )

    if show_legend:
        lines.append("    %% legend")
        lines.append('    legend_file["FILE"]:::file')
        lines.append('    legend_module["MODULE"]:::module')
        lines.append('    legend_class["CLASS"]:::klass')
        lines.append('    legend_func["FUNCTION"]:::func')
        lines.append('    legend_method["METHOD"]:::method')
        lines.append('    legend_test["TEST"]:::test')

    return "\n".join(lines) + "\n"
