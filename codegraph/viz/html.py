"""Interactive pyvis HTML renderer."""
from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import networkx as nx

from codegraph.viz._style import EDGE_STYLE, KIND_COLOR, kind_str

_DEFAULT_HEIGHT = "780px"
_DEFAULT_WIDTH = "100%"


def _shape_for_kind(kind: str) -> str:
    if kind in ("FILE", "MODULE"):
        return "box"
    if kind == "CLASS":
        return "ellipse"
    if kind == "TEST":
        return "diamond"
    return "dot"


def _node_title(attrs: dict[str, Any]) -> str:
    parts = [
        f"<b>{attrs.get('name') or attrs.get('qualname') or ''}</b>",
        f"kind: {kind_str(attrs.get('kind'))}",
        f"qualname: {attrs.get('qualname') or '-'}",
        f"file: {attrs.get('file') or '-'}:"
        f"{attrs.get('line_start') or '?'}",
        f"language: {attrs.get('language') or '-'}",
    ]
    sig = attrs.get("signature")
    if sig:
        parts.append(f"signature: {sig}")
    return "<br>".join(str(p) for p in parts)


def render_html(
    graph: nx.MultiDiGraph,
    output: Path,
    *,
    height: str = _DEFAULT_HEIGHT,
    width: str = _DEFAULT_WIDTH,
    notebook: bool = False,
) -> Path:
    """Render an interactive HTML visualization with pyvis.

    Returns the path that was written. Pyvis is a required dependency, so
    this function will only fail if the user has uninstalled it manually.
    """
    try:
        from pyvis.network import Network
    except ImportError as exc:  # pragma: no cover - pyvis is a hard dep
        raise RuntimeError(
            "pyvis is required for HTML output: pip install pyvis"
        ) from exc

    output.parent.mkdir(parents=True, exist_ok=True)

    net = Network(
        height=height,
        width=width,
        directed=True,
        notebook=notebook,
        cdn_resources="in_line",
        bgcolor="#0f172a",
        font_color="#f1f5f9",
    )
    net.barnes_hut(
        gravity=-8000,
        central_gravity=0.3,
        spring_length=120,
        spring_strength=0.04,
    )

    for nid, attrs in graph.nodes(data=True):
        kind = kind_str(attrs.get("kind"))
        color = KIND_COLOR.get(kind, "#94a3b8")
        label = str(attrs.get("name") or attrs.get("qualname") or nid[:8])
        net.add_node(
            nid,
            label=label,
            color=color,
            shape=_shape_for_kind(kind),
            title=_node_title(cast(dict[str, Any], attrs)),
            group=kind or "OTHER",
        )

    seen: set[tuple[str, str, str]] = set()
    for src, dst, data in graph.edges(data=True):
        if src not in graph.nodes or dst not in graph.nodes:
            continue
        ek = kind_str(data.get("kind"))
        key = (src, dst, ek)
        if key in seen:
            continue
        seen.add(key)
        style = EDGE_STYLE.get(ek, "solid")
        dashes = style in ("dashed", "dotted")
        width_n = 3 if style == "bold" else 1
        net.add_edge(
            src,
            dst,
            label=ek,
            arrows="to",
            dashes=dashes,
            width=width_n,
            title=ek,
        )

    html = cast(str, net.generate_html(notebook=notebook))
    output.write_text(html, encoding="utf-8")
    return output
