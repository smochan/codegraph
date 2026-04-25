"""Optional Graphviz SVG renderer (no-op if `dot` binary is missing)."""
from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

import networkx as nx

from codegraph.viz._style import EDGE_STYLE, KIND_COLOR, kind_str


class GraphvizUnavailableError(RuntimeError):
    """Raised when the graphviz Python package or `dot` binary is missing."""


def _ensure_graphviz() -> Any:
    try:
        import graphviz as _graphviz
    except ImportError as exc:
        raise GraphvizUnavailableError(
            "graphviz Python package not installed. "
            "Install with: pip install codegraph-py[viz]"
        ) from exc
    if shutil.which("dot") is None:
        raise GraphvizUnavailableError(
            "Graphviz `dot` binary not found in PATH. "
            "Install Graphviz from https://graphviz.org/download/"
        )
    return _graphviz


def render_svg(graph: nx.MultiDiGraph, output: Path) -> Path:
    """Render an SVG of ``graph`` to ``output``.

    Raises ``GraphvizUnavailableError`` if the toolchain is missing so the
    CLI can degrade gracefully.
    """
    gv = _ensure_graphviz()
    output.parent.mkdir(parents=True, exist_ok=True)

    dot = gv.Digraph(format="svg")
    dot.attr(rankdir="LR", bgcolor="white", fontname="Helvetica")
    dot.attr("node", style="filled", fontname="Helvetica", fontsize="11")
    dot.attr("edge", fontname="Helvetica", fontsize="9", color="#475569")

    for nid, attrs in graph.nodes(data=True):
        kind = kind_str(attrs.get("kind"))
        color = KIND_COLOR.get(kind, "#94a3b8")
        label = str(attrs.get("name") or attrs.get("qualname") or nid[:8])
        dot.node(
            nid,
            label=f"{kind}\\n{label}",
            fillcolor=color,
            color="#1e293b",
            fontcolor="#0f172a",
        )

    seen: set[tuple[str, str, str]] = set()
    for src, dst, data in graph.edges(data=True):
        ek = kind_str(data.get("kind"))
        key = (src, dst, ek)
        if key in seen:
            continue
        seen.add(key)
        style = EDGE_STYLE.get(ek, "solid")
        dot.edge(src, dst, label=ek, style=style)

    rendered_path = dot.render(
        filename=output.with_suffix("").name,
        directory=str(output.parent),
        cleanup=True,
    )
    rendered = Path(rendered_path)
    if rendered != output:
        rendered.replace(output)
    return output
