"""Generic High-Level-Design view derived from any repo's package structure.

Classification strategy:

1. Compute the longest common qualname prefix of all MODULE nodes (the
   "root" package). Strip it.
2. For each module, walk its qualname segments from rightmost to leftmost
   (also splitting snake_case tokens like ``store_sqlite``). The first
   token that matches a layer pattern in :data:`LAYER_CATALOG` wins.
3. If nothing matches, the module's first non-root segment becomes its own
   ad-hoc layer. This keeps the diagram useful even for domain-specific
   package names (``users``, ``billing``, ...).

The catalog patterns intentionally cover the most common architectural
concepts (cli/api, pipeline, parsers, resolve, domain, storage, analysis,
visualisation, infra). Unknown subpackages get a neutral grey "other" layer.
"""
from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
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


@dataclass(frozen=True)
class LayerSpec:
    tier: int
    id: str
    title: str
    subtitle: str
    color: str
    patterns: tuple[str, ...] = field(default_factory=tuple)


# Generic catalog: the bigger the tier number, the lower the layer sits in
# the rendered top-to-bottom flowchart.
LAYER_CATALOG: list[LayerSpec] = [
    LayerSpec(1, "cli", "CLI / API", "user-facing entrypoints", "#a78bfa", (
        "cli", "api", "routes", "handlers", "controllers", "app", "main",
        "entry", "entrypoint", "server", "rpc",
    )),
    LayerSpec(2, "pipeline", "Pipeline", "build / orchestration", "#fcd34d", (
        "pipeline", "builder", "build", "orchestrator", "scheduler",
        "jobs", "tasks", "worker", "queue", "runner",
    )),
    LayerSpec(3, "parsers", "Ingestion", "extractors / parsers", "#fb923c", (
        "parser", "parsers", "extract", "extractor", "extractors",
        "ingest", "reader", "loader", "scraper", "scrape", "import",
    )),
    LayerSpec(4, "resolve", "Resolution", "linking / binding", "#f472b6", (
        "resolve", "resolver", "resolvers", "link", "linker", "binding",
    )),
    LayerSpec(5, "domain", "Domain", "core business logic", "#c084fc", (
        "service", "services", "domain", "logic", "core", "engine",
        "usecase", "usecases",
    )),
    LayerSpec(6, "storage", "Storage", "data + persistence", "#60a5fa", (
        "store", "storage", "db", "database", "repo", "repository",
        "persistence", "schema", "sqlite", "postgres", "mysql",
        "mongo", "redis", "model", "models", "entities",
    )),
    LayerSpec(7, "analysis", "Analysis", "metrics / checks", "#34d399", (
        "analysis", "analyze", "analyzer", "metric", "metrics",
        "check", "checks", "lint", "quality", "insight", "insights",
        "stats", "report", "reporting",
    )),
    LayerSpec(8, "viz", "Visualisation", "render / dashboards", "#22d3ee", (
        "viz", "visual", "visualization", "visualisation", "render",
        "renderer", "dashboard", "ui", "frontend", "web", "html",
    )),
    LayerSpec(9, "infra", "Infra / utils", "shared helpers", "#94a3b8", (
        "util", "utils", "helper", "helpers", "common", "internal",
        "tools", "misc", "support", "config", "settings", "constants",
    )),
]

# Backward-compat: the catalog used to be exposed as ``LAYERS``.
LAYERS: list[Layer] = [
    Layer(s.id, s.title, s.subtitle, s.color) for s in LAYER_CATALOG
]

_FALLBACK_TIER = 5
_FALLBACK_COLOR = "#94a3b8"


def _split_token(seg: str) -> list[str]:
    return [p for p in re.split(r"[_\-]", seg.lower()) if p]


def _classify_segments(segments: list[str]) -> str | None:
    """Return the catalog id matching the rightmost meaningful token, else None."""
    pattern_to_id: dict[str, str] = {}
    for spec in LAYER_CATALOG:
        for pat in spec.patterns:
            pattern_to_id.setdefault(pat, spec.id)
    for seg in reversed(segments):
        token = seg.lower()
        if token in pattern_to_id:
            return pattern_to_id[token]
        for part in _split_token(seg):
            if part in pattern_to_id:
                return pattern_to_id[part]
    return None


def _common_root(qualnames: list[str]) -> str:
    if not qualnames:
        return ""
    split = [qn.split(".") for qn in qualnames if qn]
    if not split:
        return ""
    common: list[str] = []
    for segs in zip(*split, strict=False):
        if len(set(segs)) == 1:
            common.append(segs[0])
        else:
            break
    # If the only common segment IS each module's full qualname (i.e. flat
    # one-segment package set), don't strip — we'd have nothing left.
    if len(common) >= max(len(s) for s in split):
        common = common[:-1]
    return ".".join(common)


def _is_skippable_module(qn: str, file: str) -> bool:
    """Skip test modules + bare package __init__ shells from HLD."""
    if _is_test_module(qn, file):
        return True
    f = (file or "").replace("\\", "/").lower()
    return f.endswith("/__init__.py") or f == "__init__.py"


def _is_test_module(qn: str, file: str) -> bool:
    if not qn:
        return False
    f = (file or "").replace("\\", "/").lower()
    if "/tests/" in f or "/test/" in f or f.startswith("tests/") or f.startswith("test/"):
        return True
    segs = qn.split(".")
    return any(s == "tests" or s == "test" or s.startswith("test_") for s in segs)


def _file_path_to_module_qualname(graph: nx.MultiDiGraph) -> dict[str, str]:
    out: dict[str, str] = {}
    for _nid, attrs in graph.nodes(data=True):
        if kind_str(attrs.get("kind")) != "MODULE":
            continue
        f = attrs.get("file")
        qn = attrs.get("qualname")
        if isinstance(f, str) and isinstance(qn, str) and qn:
            if _is_skippable_module(qn, f):
                continue
            out[f] = qn
    return out


def _module_qualnames(graph: nx.MultiDiGraph) -> list[str]:
    return [
        str(attrs.get("qualname"))
        for _nid, attrs in graph.nodes(data=True)
        if kind_str(attrs.get("kind")) == "MODULE"
        and attrs.get("qualname")
        and not _is_skippable_module(
            str(attrs.get("qualname") or ""), str(attrs.get("file") or "")
        )
    ]


def _layer_id_for(qn: str, root: str) -> str:
    """Return the layer id for a module qualname, given the stripped root."""
    if root and (qn == root or qn.startswith(root + ".")):
        rest = qn[len(root) + 1:] if qn != root else ""
    else:
        rest = qn
    segments = [s for s in rest.split(".") if s]
    classified = _classify_segments(segments) if segments else None
    if classified:
        return classified
    if segments:
        return segments[0].lower()
    return "main"


def derive_layers(graph: nx.MultiDiGraph) -> tuple[list[Layer], str]:
    """Inspect the graph and return (ordered Layers used, root prefix)."""
    qns = _module_qualnames(graph)
    root = _common_root(qns)
    used: dict[str, int] = defaultdict(int)
    for qn in qns:
        used[_layer_id_for(qn, root)] += 1

    catalog_by_id = {s.id: s for s in LAYER_CATALOG}
    layers: list[tuple[int, str, Layer]] = []
    for lid, _count in used.items():
        spec = catalog_by_id.get(lid)
        if spec is not None:
            layers.append((spec.tier, lid, Layer(
                spec.id, spec.title, spec.subtitle, spec.color,
            )))
        else:
            # Ad-hoc layer named after the package segment.
            layers.append((_FALLBACK_TIER, lid, Layer(
                lid, lid.title(), "module group", _FALLBACK_COLOR,
            )))
    layers.sort(key=lambda t: (t[0], t[1]))
    return [lay for _t, _id, lay in layers], root


def _node_to_layer(
    graph: nx.MultiDiGraph, root: str
) -> tuple[dict[str, str], dict[str, str]]:
    """Return (node_id -> layer_id, node_id -> module_qualname)."""
    file_to_module_qn = _file_path_to_module_qualname(graph)
    node_to_layer: dict[str, str] = {}
    node_to_module_qn: dict[str, str] = {}
    for nid, attrs in graph.nodes(data=True):
        kind = kind_str(attrs.get("kind"))
        qn = str(attrs.get("qualname") or "")
        f = attrs.get("file")
        if _is_skippable_module(qn, str(f or "")):
            continue
        if kind == "MODULE" and qn:
            node_to_layer[nid] = _layer_id_for(qn, root)
            node_to_module_qn[nid] = qn
            continue
        module_qn = file_to_module_qn.get(f) if isinstance(f, str) else None
        if not module_qn and qn:
            module_qn = qn.rsplit(".", 1)[0] if "." in qn else qn
        if module_qn:
            node_to_layer[nid] = _layer_id_for(module_qn, root)
            node_to_module_qn[nid] = module_qn
    return node_to_layer, node_to_module_qn


def _short_name(qn: str) -> str:
    return qn.rsplit(".", 1)[-1] if qn else qn


@dataclass
class HldPayload:
    layers: list[dict[str, Any]]
    edges: list[dict[str, Any]]
    components: dict[str, list[dict[str, Any]]]
    modules: dict[str, dict[str, Any]]
    mermaid_layered: str
    mermaid_context: str
    metrics: dict[str, int]
    root: str = ""
    # v0.2 cross-stack data-flow surfaces (default empty so older payloads
    # remain backwards-compatible). DF1 fills routes/sql; DF2 fills fetches.
    routes: list[dict[str, Any]] = field(default_factory=list)
    sql_io: list[dict[str, Any]] = field(default_factory=list)
    fetches: list[dict[str, Any]] = field(default_factory=list)


def serialize_route_edges(graph: nx.MultiDiGraph) -> list[dict[str, Any]]:
    """Serialize ROUTE edges into the HLD payload's ``routes`` array.

    One entry per ROUTE edge. Each entry carries the handler's qualname
    plus the HTTP method/path/framework metadata captured at parse time.
    Sorted by ``(path, method)`` for stable rendering.
    """
    out: list[dict[str, Any]] = []
    for src, _dst, data in graph.edges(data=True):
        if kind_str(data.get("kind")) != "ROUTE":
            continue
        md = data.get("metadata") or {}
        if not isinstance(md, dict):
            md = {}
        handler_qn = str(graph.nodes[src].get("qualname") or "")
        out.append({
            "handler_qn": handler_qn,
            "method": str(md.get("method") or ""),
            "path": str(md.get("path") or ""),
            "framework": str(md.get("framework") or ""),
        })
    out.sort(key=lambda r: (r["path"], r["method"], r["handler_qn"]))
    return out


def serialize_sql_io_edges(graph: nx.MultiDiGraph) -> list[dict[str, Any]]:
    """Serialize READS_FROM / WRITES_TO edges into ``sql_io`` array.

    One entry per edge with ``function_qn`` (the source) and ``model_qn``
    (the resolved CLASS qualname). Unresolved edges are dropped during
    resolution, so every entry here points to a real in-repo model.
    """
    out: list[dict[str, Any]] = []
    for src, dst, data in graph.edges(data=True):
        kind = kind_str(data.get("kind"))
        if kind not in ("READS_FROM", "WRITES_TO"):
            continue
        md = data.get("metadata") or {}
        if not isinstance(md, dict):
            md = {}
        function_qn = str(graph.nodes[src].get("qualname") or "")
        model_qn = str(graph.nodes[dst].get("qualname") or "")
        if not model_qn:
            continue
        out.append({
            "function_qn": function_qn,
            "model_qn": model_qn,
            "operation": str(md.get("operation") or ""),
            "via": str(md.get("via") or ""),
            "kind": kind,
        })
    out.sort(key=lambda r: (r["function_qn"], r["model_qn"], r["operation"]))
    return out


def serialize_fetch_edges(graph: nx.MultiDiGraph) -> list[dict[str, Any]]:
    """Serialize FETCH_CALL edges into the HLD payload's `fetches` array.

    Reserved stub for the DF2 agent.
    """
    return []


def _build_modules_drilldown(
    graph: nx.MultiDiGraph,
    node_to_layer: dict[str, str],
    node_to_module: dict[str, str],
) -> dict[str, dict[str, Any]]:
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
    # Map (src_node, dst_qualname) -> edge metadata for callee_args alignment.
    call_edge_meta: dict[tuple[str, str], dict[str, Any]] = {}
    for src, dst, data in graph.edges(data=True):
        if kind_str(data.get("kind")) != "CALLS":
            continue
        src_qn = graph.nodes[src].get("qualname")
        dst_qn = graph.nodes[dst].get("qualname")
        if dst_qn:
            out_calls[src].append(str(dst_qn))
            edge_md = data.get("metadata") or {}
            if isinstance(edge_md, dict) and ("args" in edge_md or "kwargs" in edge_md):
                call_edge_meta[(src, str(dst_qn))] = {
                    "args": list(edge_md.get("args") or []),
                    "kwargs": dict(edge_md.get("kwargs") or {}),
                }
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
        callees_list = sorted(set(out_calls.get(nid, [])))[:14]
        sym: dict[str, Any] = {
            "qualname": sym_qn,
            "name": _short_name(sym_qn) or str(attrs.get("name") or ""),
            "kind": kind,
            "line": line_int,
            "fan_in": len(in_calls.get(nid, [])),
            "fan_out": len(out_calls.get(nid, [])),
            "callers": sorted(set(in_calls.get(nid, [])))[:14],
            "callees": callees_list,
        }

        # DF0/DF1.5 metadata surfacing — omit when absent on the node.
        node_md = attrs.get("metadata") or {}
        if isinstance(node_md, dict):
            if "params" in node_md:
                sym["params"] = node_md["params"]
            if "returns" in node_md:
                sym["returns"] = node_md["returns"]
            if "role" in node_md and node_md["role"] is not None:
                sym["role"] = node_md["role"]

        # callee_args parallel array, only when there ARE callees.
        if callees_list:
            callee_args: list[dict[str, Any]] = []
            for cqn in callees_list:
                meta = call_edge_meta.get((nid, cqn))
                if meta is None:
                    callee_args.append({"args": [], "kwargs": {}})
                else:
                    callee_args.append(meta)
            sym["callee_args"] = callee_args

        sym_by_module[mqn].append(sym)

    for mqn, syms in sym_by_module.items():
        syms.sort(key=lambda s: (
            0 if s["kind"] == "CLASS" else 1, -int(s["fan_in"]), s["name"]
        ))
        modules[mqn]["symbols"] = syms
    return modules


def build_hld(graph: nx.MultiDiGraph) -> HldPayload:
    layers_used, root = derive_layers(graph)
    layer_order = [lay.id for lay in layers_used]
    node_to_layer, node_to_module = _node_to_layer(graph, root)

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

    mermaid_layered = _render_layered_mermaid(layers_used, components, edges)
    mermaid_context = _render_context_mermaid(root)

    metrics = {
        "layers": sum(1 for lid in layer_order if components.get(lid)),
        "components": sum(len(v) for v in components.values()),
        "cross_layer_edges": len(edges),
        "total_cross_layer_calls": sum(
            int(cast(int, e["weight"])) for e in edges if e["kind"] == "CALLS"
        ),
    }
    return HldPayload(
        layers=[
            {"id": lay.id, "title": lay.title, "subtitle": lay.subtitle,
             "color": lay.color}
            for lay in layers_used
        ],
        edges=edges,
        components=dict(components),
        modules=_build_modules_drilldown(graph, node_to_layer, node_to_module),
        mermaid_layered=mermaid_layered,
        mermaid_context=mermaid_context,
        metrics=metrics,
        root=root,
        routes=serialize_route_edges(graph),
        sql_io=serialize_sql_io_edges(graph),
        fetches=serialize_fetch_edges(graph),
    )


_SAFE_RE = re.compile(r"[^a-zA-Z0-9]")


def _safe_id(qn: str) -> str:
    return "n_" + _SAFE_RE.sub("_", qn)[:60]


def _layer_safe(lid: str) -> str:
    return f"L_{_SAFE_RE.sub('_', lid)}"


def _render_layered_mermaid(
    layers_used: list[Layer],
    components: dict[str, list[dict[str, Any]]],
    edges: list[dict[str, Any]],
    *,
    max_per_layer: int = 8,
) -> str:
    lines: list[str] = ["flowchart TB"]
    for lay in layers_used:
        comps = components.get(lay.id, [])
        if not comps:
            continue
        lines.append(f'    subgraph {_layer_safe(lay.id)}["<b>{lay.title}</b>"]')
        lines.append("    direction LR")
        ranked = sorted(comps, key=lambda c: -int(c.get("symbols") or 0))
        shown = ranked[:max_per_layer]
        hidden = len(ranked) - len(shown)
        for c in shown:
            qn = c["qualname"]
            label = _short_name(qn)
            badge = f" · {c['symbols']}" if c["symbols"] else ""
            lines.append(f'        {_safe_id(qn)}["{label}{badge}"]')
        if hidden > 0:
            lines.append(
                f'        {_safe_id(lay.id + "_more")}(["+{hidden} more"])'
            )
        lines.append("    end")

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

    lines.append("")
    for lay in layers_used:
        if components.get(lay.id):
            lines.append(
                f"    classDef {_SAFE_RE.sub('_', lay.id)}_node "
                f"fill:{lay.color},stroke:{lay.color},color:#0b1220,rx:8,ry:8"
            )
            for c in components.get(lay.id, []):
                lines.append(
                    f"    class {_safe_id(c['qualname'])} "
                    f"{_SAFE_RE.sub('_', lay.id)}_node"
                )
            lines.append(
                f"    style {_layer_safe(lay.id)} fill:transparent,"
                f"stroke:{lay.color},stroke-width:2px,stroke-dasharray:0"
            )

    if edge_styles:
        max_w = max(w for _, w in edge_styles) or 1
        for idx, w in edge_styles:
            thickness = 1 + round((w / max_w) * 4)
            lines.append(
                f"    linkStyle {idx} stroke:#94a3b8,stroke-width:{thickness}px,"
                "fill:none"
            )

    return "\n".join(lines)


def _render_context_mermaid(root: str = "") -> str:
    proj = root or "your repo"
    return "\n".join([
        "flowchart LR",
        '    user(["<b>Developer</b><br>runs codegraph"])',
        f'    repo[("<b>{proj}</b><br>source repository")]',
        '    cli{{"<b>codegraph CLI</b><br>build · analyze · viz · serve"}}',
        '    db[("<b>.codegraph/graph.db</b><br>SQLite store")]',
        '    out[/"<b>.codegraph/explore/</b><br>HTML dashboard"/]',
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


__all__ = [
    "LAYERS",
    "LAYER_CATALOG",
    "HldPayload",
    "Layer",
    "LayerSpec",
    "build_hld",
    "derive_layers",
]
