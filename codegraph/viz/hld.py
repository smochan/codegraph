"""Hand-rolled High-Level-Design view for the codegraph repo itself.

The first iteration is intentionally specialised for ``codegraph``'s own
package layout so we can establish what "good" looks like before generalising.
The detection strategy lives in ``LAYERS`` below; cross-layer call counts are
derived live from the graph.
"""
from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from typing import Any, cast

import networkx as nx

from codegraph.viz._style import kind_str


@dataclass(frozen=True)
class Layer:
    id: str
    title: str
    subtitle: str
    color: str
    text_color: str = "#0b1220"


# Top-to-bottom layered architecture for codegraph's own repo.
# Order matters: it drives vertical placement.
LAYERS: list[Layer] = [
    Layer("cli",       "CLI",                "user-facing typer commands",  "#a78bfa"),
    Layer("pipeline",  "Build pipeline",     "orchestrator",                "#fcd34d"),
    Layer("parsers",   "Ingestion",          "language parsers (AST -> nodes)", "#fb923c"),
    Layer("resolve",   "Resolution",         "cross-file CALLS / IMPORTS",  "#f472b6"),
    Layer("storage",   "Storage",            "SQLite + NetworkX model",     "#60a5fa"),
    Layer("analysis",  "Analysis",           "metrics, cycles, hotspots, untested", "#34d399"),
    Layer("viz",       "Visualisation",      "mermaid / html / svg / dashboard", "#22d3ee"),
]

# Mapping from qualname-prefix-or-exact-match to layer id.
# Most-specific entries first.
_QUALNAME_RULES: list[tuple[str, str]] = [
    ("codegraph.cli",                "cli"),
    ("codegraph.graph.builder",      "pipeline"),
    ("codegraph.parsers.",           "parsers"),
    ("codegraph.resolve.",           "resolve"),
    ("codegraph.graph.schema",       "storage"),
    ("codegraph.graph.store_",       "storage"),
    ("codegraph.graph.",             "storage"),
    ("codegraph.analysis.",          "analysis"),
    ("codegraph.viz.",               "viz"),
]


def _layer_for_qualname(qn: str) -> str | None:
    for prefix, lid in _QUALNAME_RULES:
        if qn == prefix.rstrip(".") or qn.startswith(prefix):
            return lid
    return None


def _file_path_to_module_qualname(graph: nx.MultiDiGraph) -> dict[str, str]:
    out: dict[str, str] = {}
    for _nid, attrs in graph.nodes(data=True):
        if kind_str(attrs.get("kind")) != "MODULE":
            continue
        f = attrs.get("file")
        qn = attrs.get("qualname")
        if isinstance(f, str) and isinstance(qn, str) and qn:
            out[f] = qn
    return out


def _node_to_layer(graph: nx.MultiDiGraph) -> tuple[
    dict[str, str], dict[str, str]
]:
    """Return (node_id -> layer_id, node_id -> module_qualname)."""
    file_to_module_qn = _file_path_to_module_qualname(graph)
    node_to_layer: dict[str, str] = {}
    node_to_module_qn: dict[str, str] = {}
    for nid, attrs in graph.nodes(data=True):
        kind = kind_str(attrs.get("kind"))
        qn = str(attrs.get("qualname") or "")
        f = attrs.get("file")
        # MODULE: classify by its own qualname.
        if kind == "MODULE" and qn:
            lid = _layer_for_qualname(qn)
            if lid:
                node_to_layer[nid] = lid
                node_to_module_qn[nid] = qn
            continue
        # Symbols: classify via their file's MODULE qualname (more reliable
        # than the symbol's own qualname for nested classes / methods).
        module_qn = file_to_module_qn.get(f) if isinstance(f, str) else None
        if not module_qn and qn:
            module_qn = qn.rsplit(".", 1)[0] if "." in qn else qn
        if module_qn:
            lid = _layer_for_qualname(module_qn)
            if lid:
                node_to_layer[nid] = lid
                node_to_module_qn[nid] = module_qn
    return node_to_layer, node_to_module_qn


def _short_name(qn: str) -> str:
    return qn.rsplit(".", 1)[-1] if qn else qn


@dataclass
class HldPayload:
    layers: list[dict[str, Any]]
    edges: list[dict[str, Any]]      # cross-layer call edges with weight
    components: dict[str, list[dict[str, Any]]]  # layer_id -> modules
    modules: dict[str, dict[str, Any]]  # module_qualname -> drill-down info
    mermaid_layered: str
    mermaid_context: str
    metrics: dict[str, int]


def _build_modules_drilldown(
    graph: nx.MultiDiGraph,
    node_to_layer: dict[str, str],
    node_to_module: dict[str, str],
) -> dict[str, dict[str, Any]]:
    """Per-module symbol breakdown with direct call relations.

    Used by the HLD navigator UI to drill from layer -> module -> symbol
    -> (callers / callees) without leaving the page.
    """
    modules: dict[str, dict[str, Any]] = {}
    for nid, attrs in graph.nodes(data=True):
        if kind_str(attrs.get("kind")) != "MODULE":
            continue
        qn = str(attrs.get("qualname") or "")
        lid = node_to_layer.get(nid)
        if not qn or not lid:
            continue
        modules.setdefault(qn, {
            "qualname": qn, "name": _short_name(qn), "layer": lid,
            "file": str(attrs.get("file") or ""), "symbols": [],
        })

    out_calls: dict[str, list[str]] = defaultdict(list)
    in_calls: dict[str, list[str]] = defaultdict(list)
    for src, dst, data in graph.edges(data=True):
        if kind_str(data.get("kind")) != "CALLS":
            continue
        src_qn = graph.nodes[src].get("qualname")
        dst_qn = graph.nodes[dst].get("qualname")
        if dst_qn:
            out_calls[src].append(str(dst_qn))
        if src_qn:
            in_calls[dst].append(str(src_qn))

    sym_by_module: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for nid, attrs in graph.nodes(data=True):
        kind = kind_str(attrs.get("kind"))
        if kind not in ("FUNCTION", "METHOD", "CLASS"):
            continue
        mqn = node_to_module.get(nid)
        if not mqn or mqn not in modules:
            continue
        sym_qn = str(attrs.get("qualname") or "")
        line = attrs.get("line_start") or 0
        try:
            line_int = int(line)
        except (TypeError, ValueError):
            line_int = 0
        sym = {
            "qualname": sym_qn,
            "name": _short_name(sym_qn) or str(attrs.get("name") or ""),
            "kind": kind,
            "line": line_int,
            "fan_in": len(in_calls.get(nid, [])),
            "fan_out": len(out_calls.get(nid, [])),
            "callers": sorted(set(in_calls.get(nid, [])))[:14],
            "callees": sorted(set(out_calls.get(nid, [])))[:14],
        }
        sym_by_module[mqn].append(sym)

    for mqn, syms in sym_by_module.items():
        syms.sort(key=lambda s: (
            0 if s["kind"] == "CLASS" else 1, -int(s["fan_in"]), s["name"]
        ))
        modules[mqn]["symbols"] = syms
    return modules


def build_hld(graph: nx.MultiDiGraph) -> HldPayload:
    node_to_layer, node_to_module = _node_to_layer(graph)

    # 1. Components per layer (one card per MODULE).
    components: dict[str, list[dict[str, Any]]] = defaultdict(list)
    seen_modules: set[str] = set()
    module_symbols: dict[str, int] = defaultdict(int)
    for nid, attrs in graph.nodes(data=True):
        if kind_str(attrs.get("kind")) in ("FUNCTION", "METHOD", "CLASS"):
            mqn = node_to_module.get(nid)
            if mqn:
                module_symbols[mqn] += 1
    for nid, attrs in graph.nodes(data=True):
        if kind_str(attrs.get("kind")) != "MODULE":
            continue
        qn = str(attrs.get("qualname") or "")
        lid = node_to_layer.get(nid)
        if not lid or qn in seen_modules:
            continue
        seen_modules.add(qn)
        components[lid].append({
            "qualname": qn,
            "name": _short_name(qn),
            "file": str(attrs.get("file") or ""),
            "symbols": module_symbols.get(qn, 0),
        })
    for lid in components:
        components[lid].sort(key=lambda c: (-int(c["symbols"]), c["qualname"]))

    # 2. Cross-layer aggregated edge weights (CALLS + IMPORTS).
    pair_w: dict[tuple[str, str, str], int] = defaultdict(int)
    for src, dst, data in graph.edges(data=True):
        ek = kind_str(data.get("kind"))
        if ek not in ("CALLS", "IMPORTS"):
            continue
        sl = node_to_layer.get(src)
        dl = node_to_layer.get(dst)
        if not sl or not dl or sl == dl:
            continue
        pair_w[(sl, dl, ek)] += 1
    edges = [
        {"source": s, "target": d, "kind": k, "weight": w}
        for (s, d, k), w in sorted(pair_w.items(), key=lambda kv: -kv[1])
    ]

    # 3. Mermaid: hand-styled layered flowchart.
    mermaid_layered = _render_layered_mermaid(components, edges)
    mermaid_context = _render_context_mermaid()

    metrics = {
        "layers": sum(1 for lid in (lay.id for lay in LAYERS) if components.get(lid)),
        "components": sum(len(v) for v in components.values()),
        "cross_layer_edges": len(edges),
        "total_cross_layer_calls": sum(
            int(cast(int, e["weight"])) for e in edges if e["kind"] == "CALLS"
        ),
    }
    return HldPayload(
        layers=[
            {
                "id": lay.id,
                "title": lay.title,
                "subtitle": lay.subtitle,
                "color": lay.color,
            }
            for lay in LAYERS
        ],
        edges=edges,
        components=dict(components),
        modules=_build_modules_drilldown(graph, node_to_layer, node_to_module),
        mermaid_layered=mermaid_layered,
        mermaid_context=mermaid_context,
        metrics=metrics,
    )


# ----------------------- mermaid rendering helpers -----------------------


_SAFE_RE = re.compile(r"[^a-zA-Z0-9]")


def _safe_id(qn: str) -> str:
    return "n_" + _SAFE_RE.sub("_", qn)[:60]


def _layer_safe(lid: str) -> str:
    return f"L_{lid}"


def _render_layered_mermaid(
    components: dict[str, list[dict[str, Any]]],
    edges: list[dict[str, Any]],
) -> str:
    lines: list[str] = ["flowchart TB"]
    # Subgraphs in declared order.
    for lay in LAYERS:
        comps = components.get(lay.id, [])
        if not comps:
            continue
        lines.append(f'    subgraph {_layer_safe(lay.id)}["<b>{lay.title}</b><br>'
                     f'<span style=\'opacity:0.6\'>{lay.subtitle}</span>"]')
        lines.append("    direction LR")
        for c in comps:
            qn = c["qualname"]
            label = _short_name(qn)
            badge = f" · {c['symbols']}" if c["symbols"] else ""
            lines.append(f'        {_safe_id(qn)}["{label}{badge}"]')
        lines.append("    end")

    # Aggregate edges to single inter-layer arrows: layer -> layer with total
    # weight (sum of CALLS+IMPORTS) so we get one clean arrow per layer pair.
    layer_pair: dict[tuple[str, str], dict[str, int]] = defaultdict(
        lambda: {"calls": 0, "imports": 0}
    )
    for e in edges:
        bucket = layer_pair[(e["source"], e["target"])]
        if e["kind"] == "CALLS":
            bucket["calls"] += int(e["weight"])
        else:
            bucket["imports"] += int(e["weight"])

    edge_styles: list[tuple[int, int]] = []
    for edge_idx, ((s, d), buckets) in enumerate(sorted(layer_pair.items())):
        calls = buckets["calls"]
        imports = buckets["imports"]
        bits = []
        if calls:
            bits.append(f"{calls} calls")
        if imports:
            bits.append(f"{imports} imports")
        label = " / ".join(bits) or "uses"
        lines.append(f"    {_layer_safe(s)} --\"{label}\"--> {_layer_safe(d)}")
        edge_styles.append((edge_idx, calls + imports))

    # Style block: per-layer subgraph fill, edge thickness by weight.
    lines.append("")
    for lay in LAYERS:
        if components.get(lay.id):
            lines.append(
                f"    classDef {lay.id}_node fill:{lay.color},"
                f"stroke:#1e293b,color:{lay.text_color},rx:6,ry:6"
            )
            for c in components.get(lay.id, []):
                lines.append(f"    class {_safe_id(c['qualname'])} {lay.id}_node")
            lines.append(
                f"    style {_layer_safe(lay.id)} fill:#0f172a,stroke:{lay.color},"
                f"stroke-width:2px,color:#e2e8f0"
            )

    if edge_styles:
        max_w = max(w for _, w in edge_styles) or 1
        for idx, w in edge_styles:
            thickness = 1 + round((w / max_w) * 4)
            lines.append(
                f"    linkStyle {idx} stroke:#94a3b8,stroke-width:{thickness}px,"
                "color:#cbd5e1,fill:none"
            )

    return "\n".join(lines)


def _render_context_mermaid() -> str:
    return "\n".join([
        "flowchart LR",
        '    user(["<b>Developer</b><br>runs codegraph"])',
        '    repo[("<b>Source repo</b><br>any language")]',
        '    cli{{"<b>codegraph CLI</b><br>build · analyze · viz · explore"}}',
        '    db[("<b>.codegraph/graph.db</b><br>SQLite store")]',
        '    out[/"<b>.codegraph/explore/</b><br>HTML dashboard + node-link views"/]',
        "    user -- commands --> cli",
        "    cli -- reads --> repo",
        "    cli -- writes --> db",
        "    cli -- writes --> out",
        "    user -- opens --> out",
        "",
        "    classDef person fill:#a78bfa,stroke:#1e293b,color:#0b1220,rx:8,ry:8",
        "    classDef system fill:#22d3ee,stroke:#1e293b,color:#0b1220,rx:8,ry:8",
        "    classDef ext    fill:#fcd34d,stroke:#1e293b,color:#0b1220,rx:6,ry:6",
        "    classDef store  fill:#60a5fa,stroke:#1e293b,color:#0b1220,rx:6,ry:6",
        "    class user person",
        "    class cli system",
        "    class repo,out ext",
        "    class db store",
    ])


__all__ = ["LAYERS", "HldPayload", "Layer", "build_hld"]
