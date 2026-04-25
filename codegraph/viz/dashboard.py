"""Single-page tabbed dashboard combining diagrams + node-link views."""
from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any

import networkx as nx

from codegraph.analysis import (
    compute_metrics,
    find_cycles,
    find_dead_code,
    find_hotspots,
    find_untested,
)
from codegraph.viz._style import kind_str
from codegraph.viz.diagrams import (
    build_matrix,
    build_sankey,
    build_treemap,
    pick_flow_entry_points,
    render_flow_diagram,
    to_json,
)
from codegraph.viz.hld import build_hld


def _hotspot_scores_by_file(graph: nx.MultiDiGraph) -> dict[str, int]:
    scores: dict[str, int] = {}
    for h in find_hotspots(graph, limit=10_000):
        scores[h.file] = max(scores.get(h.file, 0), h.score)
    return scores


def _strip_noise(graph: nx.MultiDiGraph) -> nx.MultiDiGraph:
    drop = [
        nid for nid, attrs in graph.nodes(data=True)
        if (isinstance(nid, str) and nid.startswith("unresolved::"))
        or kind_str(attrs.get("kind")) == "FILE"
    ]
    if not drop:
        return graph
    g = graph.copy()
    g.remove_nodes_from(drop)
    return g


def _flows_payload(graph: nx.MultiDiGraph, limit: int = 8) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for entry in pick_flow_entry_points(graph, limit=limit):
        diagram = render_flow_diagram(graph, entry["id"])
        if not diagram:
            continue
        out.append(
            {
                "qualname": entry["qualname"],
                "file": entry["file"],
                "reason": entry["reason"],
                "mermaid": diagram,
            }
        )
    return out


def _file_stats(graph: nx.MultiDiGraph) -> list[dict[str, Any]]:
    counts: Counter[str] = Counter()
    languages: dict[str, str] = {}
    for _nid, attrs in graph.nodes(data=True):
        f = attrs.get("file")
        if not isinstance(f, str) or not f:
            continue
        counts[f] += 1
        if attrs.get("language"):
            languages[f] = str(attrs["language"])
    return [
        {"file": f, "symbols": c, "language": languages.get(f, "")}
        for f, c in counts.most_common(80)
    ]


def render_dashboard(
    graph: nx.MultiDiGraph,
    out_path: Path,
    *,
    matrix_top_n: int = 36,
    sankey_links: int = 50,
    flow_count: int = 8,
) -> Path:
    """Render the single-page dashboard to ``out_path`` (typically index.html)."""
    cleaned = _strip_noise(graph)
    metrics = compute_metrics(cleaned)
    cycles = find_cycles(cleaned)
    dead = find_dead_code(cleaned)
    untested = find_untested(cleaned)
    hotspots = find_hotspots(cleaned, limit=15)

    matrix = build_matrix(cleaned, top_n=matrix_top_n)
    sankey = build_sankey(cleaned, max_links=sankey_links)
    treemap = build_treemap(cleaned, hotspot_scores=_hotspot_scores_by_file(cleaned))
    flows = _flows_payload(cleaned, limit=flow_count)
    files = _file_stats(cleaned)
    hld = build_hld(cleaned)

    payload = {
        "metrics": {
            "nodes": metrics.total_nodes,
            "edges": metrics.total_edges,
            "unresolved": metrics.unresolved_edges,
            "by_kind": metrics.nodes_by_kind,
            "by_edge": metrics.edges_by_kind,
            "languages": metrics.languages,
        },
        "issues": {
            "cycles": cycles.total,
            "dead": len(dead),
            "untested": len(untested),
        },
        "hotspots": [
            {
                "qualname": h.qualname,
                "file": h.file,
                "fan_in": h.fan_in,
                "fan_out": h.fan_out,
                "loc": h.loc,
                "score": h.score,
            }
            for h in hotspots
        ],
        "matrix": {
            "modules": matrix.modules,
            "counts": matrix.counts,
            "max": matrix.max_count,
        },
        "sankey": sankey,
        "treemap": treemap,
        "flows": flows,
        "files": files,
        "hld": {
            "layers": hld.layers,
            "components": hld.components,
            "edges": hld.edges,
            "metrics": hld.metrics,
            "mermaid_layered": hld.mermaid_layered,
            "mermaid_context": hld.mermaid_context,
        },
    }

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(_HTML_TEMPLATE.replace("__DATA__", to_json(payload)),
                        encoding="utf-8")
    return out_path


_HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<title>codegraph dashboard</title>
<script src="https://d3js.org/d3.v7.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/d3-sankey@0.12.3/dist/d3-sankey.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/mermaid@10.9.1/dist/mermaid.min.js"></script>
<style>
:root { color-scheme: dark; --bg: #0b1220; --panel: #131c2e; --border: #243049;
        --muted: #94a3b8; --fg: #e2e8f0; --accent: #818cf8; --accent2: #22d3ee;
        --hot: #f43f5e; --warm: #f59e0b; --cool: #38bdf8; }
* { box-sizing: border-box; }
body { margin: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", system-ui,
       sans-serif; background: var(--bg); color: var(--fg); }
header { display: flex; align-items: center; justify-content: space-between;
         padding: 18px 28px; border-bottom: 1px solid var(--border);
         background: linear-gradient(180deg, #0d1426, #0b1220); position: sticky;
         top: 0; z-index: 10; }
h1 { margin: 0; font-size: 18px; font-weight: 600; letter-spacing: 0.01em; }
h1 small { color: var(--muted); font-weight: 400; margin-left: 10px; font-size: 13px; }
nav.tabs { display: flex; gap: 4px; flex-wrap: wrap; }
nav.tabs button { background: transparent; color: var(--muted); border: 1px solid
       transparent; border-radius: 6px; padding: 7px 12px; cursor: pointer;
       font-size: 13px; font-weight: 500; }
nav.tabs button:hover { color: var(--fg); background: var(--panel); }
nav.tabs button.active { color: var(--fg); background: var(--panel);
       border-color: var(--border); box-shadow: inset 0 -2px 0 var(--accent); }
main { padding: 28px; max-width: 1500px; margin: 0 auto; }
.panel { display: none; }
.panel.active { display: block; animation: fade .25s ease; }
@keyframes fade { from { opacity: 0; transform: translateY(4px); } to { opacity: 1; } }
.cards { display: grid; grid-template-columns: repeat(auto-fit, minmax(170px, 1fr));
       gap: 12px; margin-bottom: 28px; }
.card { background: var(--panel); border: 1px solid var(--border); border-radius: 10px;
       padding: 16px 18px; }
.card .num { font-size: 28px; font-weight: 600; }
.card .num.hot { color: var(--hot); }
.card .num.warm { color: var(--warm); }
.card .num.cool { color: var(--cool); }
.card .lbl { color: var(--muted); font-size: 11px; text-transform: uppercase;
       letter-spacing: 0.1em; margin-top: 6px; }
.grid2 { display: grid; grid-template-columns: 1fr 1fr; gap: 18px; }
.grid3 { display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
       gap: 18px; }
.section { background: var(--panel); border: 1px solid var(--border); border-radius: 10px;
       padding: 18px 22px; }
.section h2 { font-size: 13px; color: var(--muted); text-transform: uppercase;
       letter-spacing: 0.1em; margin: 0 0 14px; font-weight: 600; }
table { width: 100%; border-collapse: collapse; font-size: 13px; }
th, td { text-align: left; padding: 7px 8px; border-bottom: 1px solid var(--border); }
th { color: var(--muted); font-weight: 500; font-size: 11px; text-transform: uppercase;
     letter-spacing: 0.08em; }
td.num, th.num { text-align: right; font-variant-numeric: tabular-nums; }
.muted { color: var(--muted); }
code { background: #0b1220; padding: 1px 6px; border-radius: 4px; font-size: 12px;
       border: 1px solid var(--border); }
.matrix-wrap { overflow: auto; max-height: 80vh; border: 1px solid var(--border);
       border-radius: 8px; background: #0b1220; }
table.matrix { border-collapse: separate; border-spacing: 0; font-size: 11px; }
table.matrix th, table.matrix td { border: none; padding: 0; }
table.matrix .corner { position: sticky; top: 0; left: 0; z-index: 4; background: var(--panel); }
table.matrix thead th { position: sticky; top: 0; z-index: 3; background: var(--panel);
       padding: 6px 4px; min-width: 22px; text-align: center; transform: rotate(-45deg)
       translateY(8px); transform-origin: bottom left; height: 100px; vertical-align: bottom;
       font-weight: 500; color: var(--muted); white-space: nowrap; }
table.matrix tbody th { position: sticky; left: 0; z-index: 2; background: var(--panel);
       padding: 4px 10px; text-align: right; color: var(--muted); white-space: nowrap;
       font-weight: 500; max-width: 280px; overflow: hidden; text-overflow: ellipsis; }
table.matrix td.cell { width: 22px; height: 22px; text-align: center; color: #fff;
       cursor: default; }
table.matrix td.cell:hover { outline: 2px solid var(--accent); }
.legend { display: flex; align-items: center; gap: 8px; font-size: 11px; color: var(--muted);
       margin-top: 12px; }
.legend .gradient { width: 200px; height: 12px; border-radius: 6px;
       background: linear-gradient(90deg, #1e2a45, #6366f1, #f43f5e); }
#sankey, #treemap { width: 100%; height: 700px; background: #0b1220; border-radius: 8px;
       border: 1px solid var(--border); }
.flows-list { display: grid; grid-template-columns: 280px 1fr; gap: 18px; min-height: 600px; }
.flows-nav { background: var(--panel); border: 1px solid var(--border); border-radius: 10px;
       padding: 12px; overflow-y: auto; max-height: 75vh; }
.flow-item { padding: 10px 12px; border-radius: 6px; cursor: pointer;
       border: 1px solid transparent; margin-bottom: 4px; }
.flow-item:hover { background: #1a2540; }
.flow-item.active { background: #1a2540; border-color: var(--accent); }
.flow-item .qn { font-size: 13px; font-weight: 500; color: var(--fg);
       word-break: break-all; }
.flow-item .meta { font-size: 11px; color: var(--muted); margin-top: 3px; }
.flow-canvas { background: #0b1220; border: 1px solid var(--border); border-radius: 10px;
       padding: 20px; overflow: auto; min-height: 600px; display: flex;
       align-items: center; justify-content: center; }
.flow-canvas .mermaid { color: var(--fg); }
.empty { color: var(--muted); font-size: 13px; padding: 60px; text-align: center; }
input.search { width: 100%; padding: 8px 10px; background: #0b1220; color: var(--fg);
       border: 1px solid var(--border); border-radius: 6px; font-size: 13px;
       margin-bottom: 10px; }
.tooltip { position: fixed; background: #1e293b; border: 1px solid var(--border);
       padding: 8px 10px; border-radius: 6px; font-size: 12px; pointer-events: none;
       opacity: 0; transition: opacity .12s; z-index: 100; max-width: 320px; }
.tooltip.show { opacity: 1; }
.iframe-views { display: grid; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
       gap: 14px; }
.iframe-views a { display: block; background: var(--panel); border: 1px solid var(--border);
       border-radius: 10px; padding: 16px 18px; color: var(--fg); text-decoration: none; }
.iframe-views a:hover { border-color: var(--accent); }
.iframe-views .t { font-weight: 600; font-size: 14px; }
.iframe-views .d { color: var(--muted); font-size: 12px; margin-top: 4px; }
/* ---- HLD ---- */
.hld-grid { display: grid; grid-template-columns: 1fr 320px; gap: 18px;
       align-items: start; }
.hld-mini-cards { display: grid; grid-template-columns: repeat(4, 1fr);
       gap: 10px; margin-bottom: 16px; }
.hld-card { background: var(--panel); border: 1px solid var(--border);
       border-radius: 10px; padding: 14px 16px; }
.hld-card .num { font-size: 22px; font-weight: 600; }
.hld-card .lbl { color: var(--muted); font-size: 11px; text-transform: uppercase;
       letter-spacing: 0.08em; margin-top: 4px; }
.hld-canvas { background: #0f172a; border: 1px solid var(--border);
       border-radius: 12px; padding: 22px; overflow: auto; }
.hld-canvas h3 { margin: 0 0 14px; font-size: 12px; color: var(--muted);
       text-transform: uppercase; letter-spacing: 0.1em; }
.hld-canvas + .hld-canvas { margin-top: 18px; }
.hld-canvas .mermaid { display: flex; justify-content: center; }
.hld-canvas .mermaid svg { max-width: 100%; height: auto; }
.hld-side { background: var(--panel); border: 1px solid var(--border);
       border-radius: 10px; padding: 16px; position: sticky; top: 90px;
       max-height: calc(100vh - 110px); overflow-y: auto; }
.hld-side h3 { margin: 0 0 10px; font-size: 12px; color: var(--muted);
       text-transform: uppercase; letter-spacing: 0.1em; }
.layer-row { display: flex; align-items: center; gap: 10px; padding: 8px 6px;
       border-radius: 6px; }
.layer-row:hover { background: #1a2540; }
.layer-swatch { width: 14px; height: 14px; border-radius: 3px; flex: none; }
.layer-row .meta { font-size: 11px; color: var(--muted); }
.legend-edges { font-size: 12px; margin-top: 14px; }
.legend-edges .row { display: flex; justify-content: space-between;
       padding: 4px 0; border-bottom: 1px solid var(--border); }
.legend-edges .row:last-child { border-bottom: none; }
.legend-edges b { font-weight: 500; color: var(--fg); }
.help-card { background: linear-gradient(135deg,#1a2540,#0f172a);
       border: 1px solid var(--accent); border-radius: 10px; padding: 16px 18px;
       margin-bottom: 18px; font-size: 13px; color: var(--fg); }
.help-card b { color: var(--accent); }
@media (max-width: 1100px) {
  .hld-grid { grid-template-columns: 1fr; }
  .hld-side { position: static; max-height: none; }
}
</style></head><body>
<header>
  <h1>codegraph dashboard <small>multi-view code intelligence</small></h1>
  <nav class="tabs" id="tabs"></nav>
</header>
<div class="tooltip" id="tt"></div>
<main>
  <section class="panel active" id="p-overview"></section>
  <section class="panel" id="p-hld"></section>
  <section class="panel" id="p-architecture"></section>
  <section class="panel" id="p-flows"></section>
  <section class="panel" id="p-matrix"></section>
  <section class="panel" id="p-sankey"></section>
  <section class="panel" id="p-treemap"></section>
  <section class="panel" id="p-files"></section>
</main>
<script>
const DATA = __DATA__;
const TABS = [
  {id: "overview",     label: "Overview"},
  {id: "hld",          label: "HLD"},
  {id: "architecture", label: "Architecture"},
  {id: "flows",        label: "Flows"},
  {id: "matrix",       label: "Matrix"},
  {id: "sankey",       label: "Sankey"},
  {id: "treemap",      label: "Treemap"},
  {id: "files",        label: "Files"},
];

// ---- tabs ----
const tabsEl = document.getElementById("tabs");
TABS.forEach(t => {
  const b = document.createElement("button");
  b.textContent = t.label;
  b.dataset.tab = t.id;
  b.onclick = () => activate(t.id);
  tabsEl.appendChild(b);
});
function activate(id) {
  document.querySelectorAll("nav.tabs button").forEach(b =>
    b.classList.toggle("active", b.dataset.tab === id));
  document.querySelectorAll(".panel").forEach(p =>
    p.classList.toggle("active", p.id === "p-" + id));
  if (id === "sankey")  drawSankey();
  if (id === "treemap") drawTreemap();
  if (id === "flows")   ensureFlow();
  if (id === "hld")     ensureHld();
}
activate("overview");

// ---- tooltip ----
const tt = document.getElementById("tt");
function showTip(html, x, y) { tt.innerHTML = html; tt.style.left = (x+12)+"px";
  tt.style.top = (y+12)+"px"; tt.classList.add("show"); }
function hideTip() { tt.classList.remove("show"); }

// ---- overview ----
function renderOverview() {
  const m = DATA.metrics, iss = DATA.issues;
  const card = (n, l, cls) => `<div class="card"><div class="num ${cls||""}">${n}</div>`
    + `<div class="lbl">${l}</div></div>`;
  const rows = (obj) => Object.entries(obj).sort().map(([k, v]) =>
    `<tr><td>${k}</td><td class="num">${v}</td></tr>`).join("");
  const hotspots = DATA.hotspots.map(h =>
    `<tr><td><code>${h.qualname}</code></td>`
    + `<td class="muted">${h.file}</td>`
    + `<td class="num">${h.fan_in}</td><td class="num">${h.fan_out}</td>`
    + `<td class="num">${h.loc}</td><td class="num">${h.score}</td></tr>`).join("");
  document.getElementById("p-overview").innerHTML = `
    <div class="help-card">
      <b>Where to start?</b> Open the <b>HLD</b> tab for a clean layered
      architecture diagram. Use <b>Flows</b> to follow specific call chains.
      The <b>Matrix</b> shows who calls whom; the <b>Sankey</b> shows the
      heaviest flows. Cards below summarise the whole repo.
    </div>
    <div class="cards">
      ${card(m.nodes, "Nodes")}
      ${card(m.edges, "Edges")}
      ${card(m.unresolved, "Unresolved", m.unresolved ? "warm" : "")}
      ${card(iss.cycles, "Cycles", iss.cycles ? "hot" : "")}
      ${card(iss.dead, "Dead-code candidates", iss.dead ? "warm" : "")}
      ${card(iss.untested, "Untested fns", iss.untested ? "warm" : "")}
    </div>
    <div class="grid3">
      <div class="section"><h2>Nodes by kind</h2><table>${rows(m.by_kind)}</table></div>
      <div class="section"><h2>Edges by kind</h2><table>${rows(m.by_edge)}</table></div>
      <div class="section"><h2>Languages</h2><table>${rows(m.languages)}</table></div>
    </div>
    <div class="section" style="margin-top:18px"><h2>Top hotspots</h2>
      <table><tr><th>Symbol</th><th>File</th><th class="num">Fan-in</th>
      <th class="num">Fan-out</th><th class="num">LOC</th><th class="num">Score</th></tr>
      ${hotspots}</table></div>`;
}
renderOverview();

// ---- HLD (hand-rolled, lazy-rendered) ----
let hldBuilt = false;
function ensureHld() {
  if (hldBuilt) return;
  hldBuilt = true;
  const hld = DATA.hld;
  if (!hld) {
    document.getElementById("p-hld").innerHTML =
      '<div class="empty">No HLD payload — rebuild the dashboard.</div>';
    return;
  }
  const m = hld.metrics;
  const card = (n, l) => `<div class="hld-card"><div class="num">${n}</div>`
    + `<div class="lbl">${l}</div></div>`;

  const layerSide = hld.layers.filter(L => (hld.components[L.id] || []).length)
    .map(L => {
      const comps = hld.components[L.id] || [];
      return `<div class="layer-row">
        <div class="layer-swatch" style="background:${L.color}"></div>
        <div><div><b>${L.title}</b></div>
        <div class="meta">${comps.length} module${comps.length===1?"":"s"} - ${escapeHtml(L.subtitle)}</div></div>
      </div>`;
    }).join("");

  const edgeRows = hld.edges.slice(0, 20).map(e => {
    const sl = hld.layers.find(L => L.id === e.source) || {title: e.source};
    const tl = hld.layers.find(L => L.id === e.target) || {title: e.target};
    return `<div class="row"><span>${sl.title} <span class="muted">--></span> ${tl.title} `
      + `<span class="muted">(${e.kind.toLowerCase()})</span></span><b>${e.weight}</b></div>`;
  }).join("");

  document.getElementById("p-hld").innerHTML = `
    <div class="help-card">
      <b>How to read this page.</b> Top diagram = system context (who uses what).
      Below = layered architecture: each colored band is a layer, each box is a
      Python module, arrow labels show how many calls/imports cross that
      boundary. Thicker arrows = heavier traffic. Use Cmd/Ctrl + scroll to zoom.
    </div>
    <div class="hld-mini-cards">
      ${card(m.layers, "Layers")}
      ${card(m.components, "Modules")}
      ${card(m.cross_layer_edges, "Cross-layer edges")}
      ${card(m.total_cross_layer_calls, "Cross-layer calls")}
    </div>
    <div class="hld-grid">
      <div>
        <div class="hld-canvas">
          <h3>System context</h3>
          <pre class="mermaid" id="hld-context">${escapeHtml(hld.mermaid_context)}</pre>
        </div>
        <div class="hld-canvas">
          <h3>Layered architecture (live data)</h3>
          <pre class="mermaid" id="hld-layered">${escapeHtml(hld.mermaid_layered)}</pre>
        </div>
      </div>
      <aside class="hld-side">
        <h3>Layers</h3>
        ${layerSide}
        <h3 style="margin-top:18px">Top cross-layer flows</h3>
        <div class="legend-edges">${edgeRows || '<div class="muted">none</div>'}</div>
      </aside>
    </div>`;
  mermaid.run({nodes: document.querySelectorAll("#p-hld .mermaid")});
}


// ---- architecture (links to pyvis pages) ----
function renderArchitecture() {
  document.getElementById("p-architecture").innerHTML = `
    <div class="section">
      <h2>Interactive node-link explorers</h2>
      <p class="muted" style="margin:0 0 14px;font-size:13px">
        Force-directed views with in-page search and filtering.</p>
      <div class="iframe-views">
        <a href="architecture.html"><div class="t">Architecture (modules)</div>
          <div class="d">One node per file, edges aggregated by kind.</div></a>
        <a href="callgraph.html"><div class="t">Call graph</div>
          <div class="d">Functions and methods only, sized by fan-in.</div></a>
        <a href="inheritance.html"><div class="t">Inheritance</div>
          <div class="d">Classes with INHERITS / IMPLEMENTS edges.</div></a>
      </div>
    </div>`;
}
renderArchitecture();

// ---- matrix ----
function renderMatrix() {
  const m = DATA.matrix, max = m.max || 1;
  const colour = v => {
    if (!v) return "transparent";
    const t = v / max;
    const r = Math.round(30 + t * (244-30));
    const g = Math.round(42 + t * (63-42));
    const b = Math.round(69 + t * (94-69));
    return `rgb(${r},${g},${b})`;
  };
  let html = '<div class="section"><h2>Module-to-module call matrix '
    + '(rows = caller, cols = callee)</h2>';
  if (!m.modules.length) {
    html += '<div class="empty">No cross-module CALLS recorded.</div></div>';
    document.getElementById("p-matrix").innerHTML = html;
    return;
  }
  html += '<div class="matrix-wrap"><table class="matrix"><thead><tr>'
    + '<th class="corner"></th>';
  m.modules.forEach(mod => {
    html += `<th title="${mod.qualname}">${mod.name}</th>`;
  });
  html += "</tr></thead><tbody>";
  m.modules.forEach((row, i) => {
    html += `<tr><th title="${row.qualname}">${row.qualname}</th>`;
    m.counts[i].forEach((v, j) => {
      const tip = v ? `${row.name} -> ${m.modules[j].name}: ${v} call(s)` : "";
      html += `<td class="cell" data-tip="${tip}" style="background:${colour(v)}">`
            + `${v || ""}</td>`;
    });
    html += "</tr>";
  });
  html += "</tbody></table></div>";
  html += '<div class="legend"><span>0</span><div class="gradient"></div>'
    + `<span>${max}</span></div></div>`;
  const el = document.getElementById("p-matrix");
  el.innerHTML = html;
  el.querySelectorAll("td.cell").forEach(cell => {
    cell.addEventListener("mousemove", e => {
      const t = e.target.dataset.tip; if (t) showTip(t, e.clientX, e.clientY);
    });
    cell.addEventListener("mouseleave", hideTip);
  });
}
renderMatrix();

// ---- sankey ----
let sankeyDrawn = false;
function drawSankey() {
  if (sankeyDrawn) return;
  sankeyDrawn = true;
  const data = DATA.sankey;
  const host = document.getElementById("p-sankey");
  host.innerHTML = '<div class="section"><h2>Top inter-module call flows '
    + '(width = number of calls)</h2>'
    + (data.links.length
       ? '<svg id="sankey"></svg>'
       : '<div class="empty">No cross-module call flows yet.</div>')
    + '</div>';
  if (!data.links.length) return;
  const svg = d3.select("#sankey");
  const {width, height} = svg.node().getBoundingClientRect();
  const sankey = d3.sankey().nodeWidth(14).nodePadding(8)
    .extent([[1, 1], [width - 1, height - 5]]);
  const graph = sankey({
    nodes: data.nodes.map(d => Object.assign({}, d)),
    links: data.links.map(d => Object.assign({}, d)),
  });
  const colour = d3.scaleOrdinal(d3.schemeTableau10);
  svg.append("g").selectAll("rect").data(graph.nodes).join("rect")
    .attr("x", d => d.x0).attr("y", d => d.y0)
    .attr("height", d => d.y1 - d.y0).attr("width", d => d.x1 - d.x0)
    .attr("fill", d => colour(d.package || d.name))
    .on("mousemove", (e, d) => showTip(`<b>${d.qualname}</b><br>`
        + `value: ${Math.round(d.value)}`, e.clientX, e.clientY))
    .on("mouseleave", hideTip);
  svg.append("g").attr("fill", "none").selectAll("path").data(graph.links).join("path")
    .attr("d", d3.sankeyLinkHorizontal())
    .attr("stroke", d => colour(d.source.package || d.source.name))
    .attr("stroke-width", d => Math.max(1, d.width)).attr("stroke-opacity", 0.45)
    .on("mousemove", (e, d) => showTip(
        `${d.source.qualname} -> ${d.target.qualname}<br>${d.value} call(s)`,
        e.clientX, e.clientY))
    .on("mouseleave", hideTip);
  svg.append("g").style("font-size", "11px").style("fill", "#cbd5e1")
    .selectAll("text").data(graph.nodes).join("text")
    .attr("x", d => d.x0 < width / 2 ? d.x1 + 6 : d.x0 - 6)
    .attr("y", d => (d.y1 + d.y0) / 2).attr("dy", "0.35em")
    .attr("text-anchor", d => d.x0 < width / 2 ? "start" : "end")
    .text(d => d.name);
}

// ---- treemap ----
let treemapDrawn = false;
function drawTreemap() {
  if (treemapDrawn) return;
  treemapDrawn = true;
  const host = document.getElementById("p-treemap");
  host.innerHTML = '<div class="section"><h2>Codebase footprint '
    + '(area = LOC, color = hotspot score)</h2><svg id="treemap"></svg></div>';
  const root = d3.hierarchy(DATA.treemap)
    .sum(d => d.value || 0)
    .sort((a, b) => b.value - a.value);
  const svg = d3.select("#treemap");
  const {width, height} = svg.node().getBoundingClientRect();
  d3.treemap().size([width, height]).paddingInner(2).paddingTop(18).round(true)(root);
  const maxScore = d3.max(root.leaves(), d => d.data.score) || 1;
  const colour = d3.scaleSequential([0, maxScore], d3.interpolateInferno);

  const pkg = svg.append("g").selectAll("g").data(root.descendants().filter(d => d.depth === 1))
    .join("g").attr("transform", d => `translate(${d.x0},${d.y0})`);
  pkg.append("rect").attr("width", d => d.x1 - d.x0).attr("height", d => d.y1 - d.y0)
    .attr("fill", "#1e293b").attr("stroke", "#334155");
  pkg.append("text").attr("x", 6).attr("y", 12).attr("fill", "#cbd5e1")
    .style("font-size", "11px").style("font-weight", "600").text(d => d.data.name);

  const leaf = svg.append("g").selectAll("g").data(root.leaves())
    .join("g").attr("transform", d => `translate(${d.x0},${d.y0})`);
  leaf.append("rect").attr("width", d => Math.max(0, d.x1 - d.x0))
    .attr("height", d => Math.max(0, d.y1 - d.y0))
    .attr("fill", d => d.data.score ? colour(d.data.score) : "#334155")
    .attr("stroke", "#0b1220").attr("stroke-width", 0.5)
    .on("mousemove", (e, d) => showTip(
       `<b>${d.data.name}</b><br>${d.data.file}<br>LOC: ${d.data.value}`
       + `<br>symbols: ${d.data.symbols}<br>hotspot score: ${d.data.score}`,
       e.clientX, e.clientY))
    .on("mouseleave", hideTip);
  leaf.append("text").attr("x", 4).attr("y", 12).attr("fill", "#fff")
    .style("font-size", "10px").style("pointer-events", "none")
    .text(d => (d.x1 - d.x0 > 60 && d.y1 - d.y0 > 18) ? d.data.name.split(".").pop() : "");
}

// ---- flows ----
mermaid.initialize({startOnLoad: false, theme: "dark",
  themeVariables: {fontSize: "13px", primaryColor: "#1e293b",
    primaryTextColor: "#e2e8f0", lineColor: "#475569"}});
let activeFlow = -1;
function ensureFlow() {
  if (DATA.flows.length === 0 && document.getElementById("p-flows").innerHTML) return;
  const host = document.getElementById("p-flows");
  if (host.dataset.built) return;
  host.dataset.built = "1";
  if (!DATA.flows.length) {
    host.innerHTML = '<div class="empty">No call chains found yet. '
      + 'Run <code>codegraph build</code> on a real codebase.</div>';
    return;
  }
  let html = '<div class="flows-list"><div class="flows-nav">'
    + '<input class="search" id="flow-search" placeholder="Filter entry points...">';
  DATA.flows.forEach((f, i) => {
    html += `<div class="flow-item" data-i="${i}">`
      + `<div class="qn">${escapeHtml(f.qualname)}</div>`
      + `<div class="meta">${escapeHtml(f.reason)} - ${escapeHtml(f.file)}</div></div>`;
  });
  html += '</div><div class="flow-canvas" id="flow-canvas">'
    + '<div class="muted">Pick an entry point on the left.</div></div></div>';
  host.innerHTML = html;
  host.querySelectorAll(".flow-item").forEach(el => {
    el.onclick = () => selectFlow(parseInt(el.dataset.i, 10));
  });
  document.getElementById("flow-search").addEventListener("input", e => {
    const q = e.target.value.toLowerCase();
    host.querySelectorAll(".flow-item").forEach(el => {
      el.style.display = el.textContent.toLowerCase().includes(q) ? "" : "none";
    });
  });
  selectFlow(0);
}
function selectFlow(i) {
  if (i === activeFlow) return;
  activeFlow = i;
  document.querySelectorAll("#p-flows .flow-item").forEach(el =>
    el.classList.toggle("active", parseInt(el.dataset.i, 10) === i));
  const flow = DATA.flows[i];
  const canvas = document.getElementById("flow-canvas");
  canvas.innerHTML = `<pre class="mermaid">${escapeHtml(flow.mermaid)}</pre>`;
  mermaid.run({nodes: canvas.querySelectorAll(".mermaid")});
}
function escapeHtml(s) { return String(s).replace(/[&<>"]/g, c =>
  ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c])); }

// ---- files ----
function renderFiles() {
  const rows = DATA.files.map(f => {
    const slug = f.file.replace(/[^a-zA-Z0-9_-]+/g, "_").replace(/^_|_$/g, "") || "file";
    return `<tr><td><a href="files/${slug}.html" style="color:var(--accent)">`
      + `<code>${escapeHtml(f.file)}</code></a></td>`
      + `<td class="muted">${f.language}</td>`
      + `<td class="num">${f.symbols}</td></tr>`;
  }).join("");
  document.getElementById("p-files").innerHTML = `
    <div class="section"><h2>Files</h2><table>
    <tr><th>Path</th><th>Language</th><th class="num">Symbols</th></tr>
    ${rows}</table></div>`;
}
renderFiles();
</script></body></html>"""


__all__ = ["render_dashboard"]
