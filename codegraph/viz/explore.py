"""Multi-view interactive dashboard ("explore" mode).

Generates a folder of linked HTML pages so users can navigate a real-world
graph at multiple zoom levels:

* ``index.html``        — landing page with key metrics + links
* ``architecture.html`` — module-level diagram (one node per module, edges
  aggregated by kind with weight = count)
* ``callgraph.html``    — only functions + methods, with pyvis filter UI
* ``inheritance.html``  — only classes, INHERITS / IMPLEMENTS edges
* ``files/<slug>.html`` — per-file detail (module + its symbols + 1-hop
  neighbours so cross-file calls are visible in context)

Each page is self-contained (pyvis ``cdn_resources="in_line"``) so the
folder can be opened over file:// without a server.
"""
from __future__ import annotations

import html
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

import networkx as nx

from codegraph.viz._style import EDGE_STYLE, KIND_COLOR, kind_str

_DEFINITION_KINDS: frozenset[str] = frozenset(
    {"MODULE", "CLASS", "FUNCTION", "METHOD", "TEST"}
)
_CALLABLE_KINDS: frozenset[str] = frozenset({"FUNCTION", "METHOD"})
_NOISE_KINDS: frozenset[str] = frozenset({"FILE"})

_SLUG_RE = re.compile(r"[^a-zA-Z0-9_-]+")


@dataclass
class ExploreResult:
    out_dir: Path
    pages: list[Path]


def _slug(name: str) -> str:
    return _SLUG_RE.sub("_", name).strip("_") or "page"


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
        f"<b>{html.escape(str(attrs.get('name') or attrs.get('qualname') or ''))}</b>",
        f"kind: {kind_str(attrs.get('kind'))}",
        f"qualname: {html.escape(str(attrs.get('qualname') or '-'))}",
        f"file: {html.escape(str(attrs.get('file') or '-'))}:"
        f"{attrs.get('line_start') or '?'}",
    ]
    sig = attrs.get("signature")
    if sig:
        parts.append(f"sig: {html.escape(str(sig))}")
    return "<br>".join(parts)


def _strip_noise(graph: nx.MultiDiGraph) -> nx.MultiDiGraph:
    """Drop unresolved::* phantom nodes and FILE nodes."""
    drop: list[str] = [
        nid for nid, attrs in graph.nodes(data=True)
        if (isinstance(nid, str) and nid.startswith("unresolved::"))
        or kind_str(attrs.get("kind")) in _NOISE_KINDS
    ]
    if not drop:
        return graph
    out = cast(nx.MultiDiGraph, graph.copy())
    out.remove_nodes_from(drop)
    return out


def _kind_subgraph(
    graph: nx.MultiDiGraph, kinds: frozenset[str]
) -> nx.MultiDiGraph:
    keep = {
        nid for nid, attrs in graph.nodes(data=True)
        if kind_str(attrs.get("kind")) in kinds
    }
    return cast(nx.MultiDiGraph, graph.subgraph(keep).copy())


def _aggregate_to_modules(graph: nx.MultiDiGraph) -> nx.DiGraph:
    """Collapse every CLASS/FUNCTION/METHOD into its parent MODULE.

    The resulting DiGraph has one node per MODULE plus aggregated edges
    keyed by (kind) with ``weight`` = count of original edges.
    """
    # Map any node id -> module id (its file's module node).
    module_by_file: dict[str, str] = {}
    for nid, attrs in graph.nodes(data=True):
        if kind_str(attrs.get("kind")) == "MODULE":
            file_path = attrs.get("file")
            if isinstance(file_path, str):
                module_by_file[file_path] = nid
    node_to_module: dict[str, str] = {}
    for nid, attrs in graph.nodes(data=True):
        kind = kind_str(attrs.get("kind"))
        if kind == "MODULE":
            node_to_module[nid] = nid
            continue
        file_path = attrs.get("file")
        if isinstance(file_path, str) and file_path in module_by_file:
            node_to_module[nid] = module_by_file[file_path]

    out: nx.DiGraph = nx.DiGraph()
    for mid, attrs in graph.nodes(data=True):
        if kind_str(attrs.get("kind")) != "MODULE":
            continue
        package = ""
        qn = str(attrs.get("qualname") or "")
        if "." in qn:
            package = qn.rsplit(".", 1)[0]
        out.add_node(
            mid,
            label=str(attrs.get("name") or qn or mid[:8]),
            qualname=qn,
            file=str(attrs.get("file") or ""),
            language=str(attrs.get("language") or ""),
            kind="MODULE",
            package=package,
            is_test=bool((attrs.get("metadata") or {}).get("is_test")),
            symbols=0,
        )

    # Count symbols per module.
    sym_counter: Counter[str] = Counter()
    for nid, attrs in graph.nodes(data=True):
        kind = kind_str(attrs.get("kind"))
        if kind in ("FUNCTION", "METHOD", "CLASS"):
            mid = node_to_module.get(nid)
            if mid is not None:
                sym_counter[mid] += 1
    for mid, count in sym_counter.items():
        if mid in out:
            out.nodes[mid]["symbols"] = count

    # Aggregate edges.
    edge_w: dict[tuple[str, str, str], int] = defaultdict(int)
    for src, dst, data in graph.edges(data=True):
        ek = kind_str(data.get("kind"))
        if ek in ("DEFINED_IN", "PARAM_OF"):
            continue
        src_m = node_to_module.get(src)
        dst_m = node_to_module.get(dst)
        if not src_m or not dst_m or src_m == dst_m:
            continue
        edge_w[(src_m, dst_m, ek)] += 1
    for (s, d, k), w in edge_w.items():
        out.add_edge(s, d, kind=k, weight=w)
    return out


def _render_pyvis(
    graph: nx.Graph,
    output: Path,
    *,
    title: str,
    select_menu: bool = False,
    filter_menu: bool = False,
    node_size_attr: str | None = None,
) -> Path:
    """Lower-level pyvis renderer used by every dashboard page."""
    from pyvis.network import Network

    output.parent.mkdir(parents=True, exist_ok=True)
    net = Network(
        height="780px",
        width="100%",
        directed=True,
        cdn_resources="in_line",
        bgcolor="#0f172a",
        font_color="#f1f5f9",
        select_menu=select_menu,
        filter_menu=filter_menu,
        heading=title,
    )
    net.barnes_hut(
        gravity=-12000,
        central_gravity=0.25,
        spring_length=140,
        spring_strength=0.04,
    )

    for nid, attrs in graph.nodes(data=True):
        kind = kind_str(attrs.get("kind"))
        color = KIND_COLOR.get(kind, "#94a3b8")
        label = str(
            attrs.get("label") or attrs.get("name") or attrs.get("qualname") or nid[:8]
        )
        title_html = (
            attrs.get("title")
            if "title" in attrs
            else _node_title(cast(dict[str, Any], attrs))
        )
        size: float = 14.0
        if node_size_attr is not None:
            raw = attrs.get(node_size_attr) or 0
            try:
                size = 12.0 + float(raw) * 2.0
            except (TypeError, ValueError):
                size = 14.0
        kwargs: dict[str, Any] = {
            "label": label,
            "color": color,
            "shape": _shape_for_kind(kind),
            "title": title_html,
            "group": kind or "OTHER",
            "size": size,
        }
        # Surface arbitrary string attributes so filter_menu can use them.
        for key in ("file", "language", "package", "qualname"):
            val = attrs.get(key)
            if isinstance(val, str) and val:
                kwargs[key] = val
        net.add_node(nid, **kwargs)

    seen: set[tuple[str, str, str]] = set()
    if isinstance(graph, nx.MultiDiGraph):
        edge_iter = (
            (s, d, data) for s, d, _key, data in graph.edges(keys=True, data=True)
        )
    else:
        edge_iter = ((s, d, data) for s, d, data in graph.edges(data=True))
    for src, dst, data in edge_iter:
        ek = kind_str(data.get("kind"))
        edge_key: tuple[str, str, str] = (src, dst, ek)
        if edge_key in seen:
            continue
        seen.add(edge_key)
        weight = int(data.get("weight") or 1)
        style = EDGE_STYLE.get(ek, "solid")
        dashes = style in ("dashed", "dotted")
        width_n = 1 + min(6, weight - 1) if weight > 1 else (3 if style == "bold" else 1)
        net.add_edge(
            src,
            dst,
            label=ek if weight == 1 else f"{ek} x{weight}",
            arrows="to",
            dashes=dashes,
            width=width_n,
            title=f"{ek} (weight={weight})",
        )

    html_text = cast(str, net.generate_html(notebook=False))
    html_text = _inject_pyvis_theme_switch(html_text)
    output.write_text(html_text, encoding="utf-8")
    return output


_PYVIS_THEME_INJECT = """
<style id="cg-pyvis-theme">
  html.cg-light, html.cg-light body { background: #f5f7fb !important; color: #0f172a !important; }
  html.cg-light .card, html.cg-light #mynetwork { background: #ffffff !important; }
  html.cg-light h1, html.cg-light h2, html.cg-light h3, html.cg-light p { color: #0f172a !important; }
  html.cg-light #mynetwork { border: 1px solid #e2e8f0 !important; border-radius: 12px; }
  body { transition: background 200ms ease, color 200ms ease; }
  #cg-theme-toggle {
    position: fixed; top: 14px; right: 14px; z-index: 9999;
    background: rgba(15,23,42,.65); color: #f1f5f9; border: 1px solid #334155;
    border-radius: 8px; padding: 6px 12px; cursor: pointer; font: 500 12px/1 system-ui;
  }
  html.cg-light #cg-theme-toggle { background: #ffffff; color: #0f172a; border-color: #cbd5e1; }
</style>
<script>
(function(){
  function applyTheme(t){
    var root = document.documentElement;
    if (t === 'light') root.classList.add('cg-light');
    else root.classList.remove('cg-light');
    if (window.network && window.network.setOptions) {
      window.network.setOptions({
        nodes: { font: { color: t === 'light' ? '#0f172a' : '#f1f5f9' } },
        edges: { font: { color: t === 'light' ? '#475569' : '#cbd5e1' } },
      });
    }
    var mn = document.getElementById('mynetwork');
    if (mn) mn.style.background = t === 'light' ? '#ffffff' : '#0f172a';
    try { localStorage.setItem('cg-pyvis-theme', t); } catch(e){}
  }
  var p = new URLSearchParams(location.search);
  var initial = p.get('theme');
  if (!initial) {
    try { initial = localStorage.getItem('cg-pyvis-theme'); } catch(e){}
  }
  if (!initial) initial = 'dark';
  function ready(){
    applyTheme(initial);
    var btn = document.createElement('button');
    btn.id = 'cg-theme-toggle';
    btn.textContent = initial === 'light' ? '☾ dark' : '☀ light';
    btn.onclick = function(){
      var cur = document.documentElement.classList.contains('cg-light') ? 'light' : 'dark';
      var nxt = cur === 'light' ? 'dark' : 'light';
      applyTheme(nxt);
      btn.textContent = nxt === 'light' ? '☾ dark' : '☀ light';
    };
    document.body.appendChild(btn);
  }
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', ready);
  } else { ready(); }
})();
</script>
"""


def _inject_pyvis_theme_switch(html_text: str) -> str:
    """Inject a light/dark toggle into pyvis-generated HTML."""
    if "cg-pyvis-theme" in html_text:
        return html_text
    needle = "</body>"
    if needle in html_text:
        return html_text.replace(needle, _PYVIS_THEME_INJECT + needle, 1)
    return html_text + _PYVIS_THEME_INJECT


def render_explore(
    graph: nx.MultiDiGraph,
    out_dir: Path,
    *,
    top_files: int = 25,
    callgraph_limit: int = 400,
) -> ExploreResult:
    """Build the multi-page explorer dashboard at ``out_dir``."""
    out_dir.mkdir(parents=True, exist_ok=True)
    files_dir = out_dir / "files"
    files_dir.mkdir(exist_ok=True)

    cleaned = _strip_noise(graph)
    pages: list[Path] = []
    nav: list[tuple[str, Path, str]] = []

    # 1. Architecture (module-level).
    arch = _aggregate_to_modules(cleaned)
    arch_path = out_dir / "architecture.html"
    _render_pyvis(
        arch,
        arch_path,
        title="Architecture — modules and aggregated dependencies",
        select_menu=True,
        filter_menu=True,
        node_size_attr="symbols",
    )
    pages.append(arch_path)
    nav.append((
        "Architecture",
        arch_path,
        "module-level — one node per file, edges aggregated by kind with thickness = count",
    ))

    # 2. Call graph (functions + methods only, with hotspot sizing).
    callgraph = _kind_subgraph(cleaned, _CALLABLE_KINDS)
    # Tag with fan-in for sizing.
    for nid in callgraph.nodes():
        callgraph.nodes[nid]["fan_in"] = sum(
            1 for _s, _d, k in callgraph.in_edges(nid, keys=True)
            if k == "CALLS"
        )
    if callgraph.number_of_nodes() > callgraph_limit:
        degree_sorted = sorted(callgraph.degree(), key=lambda x: x[1], reverse=True)
        top_ids = {n for n, _ in degree_sorted[:callgraph_limit]}
        callgraph = cast(nx.MultiDiGraph, callgraph.subgraph(top_ids).copy())
    callgraph_path = out_dir / "callgraph.html"
    _render_pyvis(
        callgraph,
        callgraph_path,
        title="Call graph — functions and methods (size = fan-in)",
        select_menu=True,
        filter_menu=True,
        node_size_attr="fan_in",
    )
    pages.append(callgraph_path)
    nav.append((
        "Call graph",
        callgraph_path,
        "every CALLS edge between functions/methods, node size = number of callers",
    ))

    # 3. Inheritance.
    classes = _kind_subgraph(cleaned, frozenset({"CLASS"}))
    inh_path = out_dir / "inheritance.html"
    _render_pyvis(
        classes,
        inh_path,
        title="Inheritance — classes, INHERITS / IMPLEMENTS edges",
        select_menu=True,
        filter_menu=True,
    )
    pages.append(inh_path)
    nav.append((
        "Inheritance",
        inh_path,
        "every CLASS in the repo, only INHERITS / IMPLEMENTS edges drawn",
    ))

    # 4. Per-file detail pages — top files by node count.
    file_node_counts: Counter[str] = Counter()
    for _nid, attrs in cleaned.nodes(data=True):
        fp = attrs.get("file")
        if isinstance(fp, str) and fp:
            file_node_counts[fp] += 1
    file_pages: list[tuple[str, Path, int]] = []
    for file_path, n_nodes in file_node_counts.most_common(top_files):
        keep: set[str] = set()
        for nid, attrs in cleaned.nodes(data=True):
            if attrs.get("file") == file_path:
                keep.add(nid)
        # Add 1-hop neighbours so cross-file calls are visible in context.
        neighbour_set: set[str] = set()
        for nid in keep:
            for src, _dst, _key in cleaned.in_edges(nid, keys=True):
                neighbour_set.add(src)
            for _src, dst, _key in cleaned.out_edges(nid, keys=True):
                neighbour_set.add(dst)
        sub = cast(
            nx.MultiDiGraph, cleaned.subgraph(keep | neighbour_set).copy()
        )
        slug = _slug(file_path)
        page_path = files_dir / f"{slug}.html"
        _render_pyvis(
            sub,
            page_path,
            title=f"File detail: {file_path}",
            select_menu=True,
            filter_menu=True,
        )
        file_pages.append((file_path, page_path, n_nodes))
        pages.append(page_path)

    # 5. Index (built last so it can reference everything).
    from codegraph.viz.dashboard import render_dashboard
    index_path = render_dashboard(cleaned, out_dir / "index.html")
    pages.insert(0, index_path)

    return ExploreResult(out_dir=out_dir, pages=pages)


__all__ = ["ExploreResult", "render_explore"]
