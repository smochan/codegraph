/* codegraph dashboard - vanilla JS app */
'use strict';

// ----- Theme + sidebar persistence (apply early) -----
(function applyEarlyPrefs() {
  try {
    const t = localStorage.getItem('cg-theme');
    if (t === 'light') document.documentElement.classList.add('theme-light');
    if (localStorage.getItem('cg-sb') === 'collapsed')
      document.documentElement.classList.add('sb-collapsed');
  } catch (e) { /* ignore */ }
})();

const state = {
  data: null,
  view: 'overview',
  flowSel: 0,
};

const VIEWS = [
  { section: 'Insights' },
  { id: 'overview',     label: 'Overview',     icon: 'layout-dashboard' },
  { id: 'hld',          label: 'HLD',          icon: 'layers' },
  { id: 'flows',        label: 'Call flows',   icon: 'git-fork' },
  { section: 'Diagrams' },
  { id: 'matrix',       label: 'Matrix',       icon: 'grid-3x3' },
  { id: 'sankey',       label: 'Sankey',       icon: 'waves' },
  { id: 'treemap',      label: 'Treemap',      icon: 'square-stack' },
  { section: 'Browse' },
  { id: 'architecture', label: 'Explorers',    icon: 'compass' },
  { id: 'files',        label: 'Files',        icon: 'folder-tree' },
];

// ---- Tooltip ----
const tt = document.getElementById('tooltip');
function showTip(html, x, y) {
  tt.innerHTML = html;
  const r = tt.getBoundingClientRect();
  let lx = x + 14, ly = y + 14;
  if (lx + r.width > innerWidth - 8) lx = x - r.width - 14;
  if (ly + r.height > innerHeight - 8) ly = y - r.height - 14;
  tt.style.left = lx + 'px';
  tt.style.top = ly + 'px';
  tt.style.opacity = '1';
}
function hideTip() { tt.style.opacity = '0'; }

// ---- Toast ----
function toast(msg, kind) {
  const host = document.getElementById('toast-host');
  const el = document.createElement('div');
  el.className = 'toast ' + (kind || '');
  el.textContent = msg;
  host.appendChild(el);
  setTimeout(() => { el.style.opacity = '0'; el.style.transition = 'opacity 0.3s';
    setTimeout(() => el.remove(), 350); }, 2400);
}

// ---- Mermaid ----
function mermaidThemeVars() {
  const light = document.documentElement.classList.contains('theme-light');
  return light
    ? { fontFamily: 'Inter, system-ui, sans-serif', fontSize: '14px',
        background: 'transparent',
        primaryColor: '#eef2ff', primaryTextColor: '#0f172a',
        primaryBorderColor: '#a5b4fc', lineColor: '#6366f1',
        secondaryColor: '#f5f3ff', tertiaryColor: '#ffffff',
        clusterBkg: 'rgba(238,242,255,0.7)', clusterBorder: '#a5b4fc',
        nodeBorder: '#a5b4fc', mainBkg: '#eef2ff',
        edgeLabelBackground: '#ffffff', titleColor: '#1e293b' }
    : { fontFamily: 'Inter, system-ui, sans-serif', fontSize: '14px',
        background: 'transparent',
        primaryColor: '#1d2942', primaryTextColor: '#e6ecf5',
        primaryBorderColor: '#3b4a6a', lineColor: '#5b6b8c',
        secondaryColor: '#161f33', tertiaryColor: '#0f1626',
        clusterBkg: 'rgba(15,22,38,0.6)', clusterBorder: '#3b4a6a',
        nodeBorder: '#3b4a6a', mainBkg: '#1d2942',
        edgeLabelBackground: '#0a0f1c', titleColor: '#c4cfe2' };
}
function initMermaid() {
  mermaid.initialize({
    startOnLoad: false, theme: 'base',
    themeVariables: mermaidThemeVars(),
    flowchart: { padding: 18, nodeSpacing: 38, rankSpacing: 54,
                 curve: 'basis', htmlLabels: true, useMaxWidth: true },
  });
}
initMermaid();

// ---- Sidebar ----
function buildNav() {
  const nav = document.getElementById('nav');
  VIEWS.forEach(v => {
    if (v.section) {
      const h = document.createElement('div');
      h.className = 'nav-section'; h.textContent = v.section;
      nav.appendChild(h);
      return;
    }
    const item = document.createElement('div');
    item.className = 'nav-item';
    item.dataset.id = v.id;
    item.innerHTML = `<i data-lucide="${v.icon}"></i><span>${v.label}</span>`;
    item.onclick = () => activate(v.id);
    nav.appendChild(item);
  });
  lucide.createIcons();
}

function activate(id) {
  state.view = id;
  document.querySelectorAll('.nav-item').forEach(el =>
    el.classList.toggle('active', el.dataset.id === id));
  const view = VIEWS.find(v => v.id === id);
  document.getElementById('page-title').textContent = view?.label || 'View';
  document.getElementById('crumb').textContent =
    VIEWS.find(v => v.section && VIEWS.indexOf(v) <
      VIEWS.findIndex(x => x.id === id))?.section || 'codegraph';
  render(id);
  history.replaceState({}, '', '#' + id);
}

// ---- Header stats ----
function setHeaderStats() {
  const m = state.data.metrics, iss = state.data.issues;
  document.getElementById('header-stats').innerHTML = `
    <span class="pill">${m.nodes} nodes</span>
    <span class="pill">${m.edges} edges</span>
    ${iss.cycles ? `<span class="pill pill-hot">${iss.cycles} cycles</span>` : ''}
    ${iss.dead ? `<span class="pill pill-warm">${iss.dead} dead</span>` : ''}
  `;
}

// ---- Views ----
function render(id) {
  const host = document.getElementById('view-host');
  host.innerHTML = '';
  const fn = VIEW_RENDERERS[id];
  if (!fn) { host.innerHTML = '<div class="p-8 text-ink-200">Unknown view.</div>'; return; }
  fn(host);
  lucide.createIcons();
}

const VIEW_RENDERERS = {
  overview: renderOverview,
  hld: renderHld,
  flows: renderFlows,
  matrix: renderMatrix,
  sankey: renderSankey,
  treemap: renderTreemap,
  architecture: renderArchitecture,
  files: renderFiles,
};

// ---------- Overview ----------
function renderOverview(host) {
  const m = state.data.metrics, iss = state.data.issues;
  const card = (n, l, accent) => `
    <div class="stat-card">
      <div class="stat-num ${accent || ''}">${n}</div>
      <div class="stat-lbl">${l}</div>
    </div>`;
  const rows = obj => Object.entries(obj).sort((a,b)=>b[1]-a[1]).map(([k,v]) =>
    `<tr><td>${esc(k)}</td><td class="num">${v}</td></tr>`).join('');
  const hot = state.data.hotspots.map(h => `
    <tr>
      <td><span class="qn-mono text-[12.5px]">${formatQn(h.qualname, {maxParts: 4})}</span></td>
      <td class="text-ink-200"><code>${esc(h.file)}</code></td>
      <td class="num">${h.fan_in}</td>
      <td class="num">${h.fan_out}</td>
      <td class="num">${h.loc}</td>
      <td class="num"><span class="pill ${h.score>200?'pill-hot':h.score>80?'pill-warm':''}">${h.score}</span></td>
    </tr>`).join('');

  host.innerHTML = `
    <div class="p-8 space-y-6 max-w-7xl mx-auto">
      <div class="help-card">
        <i data-lucide="sparkles" class="icon w-4 h-4"></i>
        <div><b>Where to start.</b> Open <b>HLD</b> for a clean layered diagram of how the codebase is wired.
        Use <b>Call flows</b> to step through specific functions, or <b>Matrix</b> to see who calls whom in one glance.</div>
      </div>
      <div class="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-3">
        ${card(m.nodes, 'Nodes')}
        ${card(m.edges, 'Edges')}
        ${card(m.unresolved, 'Unresolved', m.unresolved ? 'text-accent-amber' : '')}
        ${card(iss.cycles, 'Cycles', iss.cycles ? 'text-accent-rose' : '')}
        ${card(iss.dead, 'Dead-code candidates', iss.dead ? 'text-accent-amber' : '')}
        ${card(iss.untested, 'Untested fns', iss.untested ? 'text-accent-amber' : '')}
      </div>
      <div class="grid grid-cols-1 md:grid-cols-3 gap-4">
        <div class="panel p-5"><div class="section-h"><h2>Nodes by kind</h2></div>
          <table class="data">${rows(m.by_kind)}</table></div>
        <div class="panel p-5"><div class="section-h"><h2>Edges by kind</h2></div>
          <table class="data">${rows(m.by_edge)}</table></div>
        <div class="panel p-5"><div class="section-h"><h2>Languages</h2></div>
          <table class="data">${rows(m.languages)}</table></div>
      </div>
      <div class="panel p-5">
        <div class="section-h"><h2>Top hotspots</h2>
          <span class="text-[11px] text-ink-200">score = fan_in*2 + fan_out + LOC/50</span></div>
        <table class="data">
          <thead><tr><th>Symbol</th><th>File</th><th class="num">Fan-in</th>
            <th class="num">Fan-out</th><th class="num">LOC</th><th class="num">Score</th></tr></thead>
          <tbody>${hot}</tbody>
        </table>
      </div>
    </div>`;
}

// ---------- HLD ----------
const hldNav = { layer: null, module: null, symbol: null };

function renderHld(host) {
  const hld = state.data.hld;
  if (!hld) { host.innerHTML = '<div class="text-app-2 p-8">No HLD payload.</div>'; return; }
  const m = hld.metrics;
  const card = (n, l) => `
    <div class="stat-card"><div class="stat-num">${n}</div>
    <div class="stat-lbl">${l}</div></div>`;

  host.innerHTML = `
    <div class="p-8 space-y-6 max-w-7xl mx-auto">
      <div class="help-card">
        <i data-lucide="map" class="icon w-4 h-4"></i>
        <div><b>How to read this.</b> Top = system context. Below = the layered architecture (heaviest modules per layer; <code>+N more</code> means more exist — see Navigator). The <b>Navigator</b> drills <i>Layer → Module → Symbol</i>; selecting a symbol draws a live focus graph of who calls it and what it calls.</div>
      </div>
      <div class="grid grid-cols-2 md:grid-cols-4 gap-3">
        ${card(m.layers, 'Layers')}
        ${card(m.components, 'Modules')}
        ${card(m.cross_layer_edges, 'Cross-layer edges')}
        ${card(m.total_cross_layer_calls, 'Cross-layer calls')}
      </div>
      <div class="panel p-5">
        <div class="section-h"><h2>System context</h2>
          <span class="text-[11px] text-app-2">C4-style</span></div>
        <div class="mermaid-host" style="min-height:240px"><pre class="mermaid">${esc(hld.mermaid_context)}</pre></div>
      </div>
      <div class="panel p-5">
        <div class="section-h"><h2>Layered architecture</h2>
          <span class="text-[11px] text-app-2">top modules per layer · <code>+N more</code> = drill in Navigator</span></div>
        <div class="mermaid-host" style="min-height:520px"><pre class="mermaid">${esc(hld.mermaid_layered)}</pre></div>
      </div>
      <div class="panel p-5">
        <div class="section-h">
          <h2>Navigator</h2>
          <div id="hld-crumb" class="hld-crumb"></div>
        </div>
        <div class="hld-cols">
          <div class="hld-col" id="hld-col-layers"></div>
          <div class="hld-col" id="hld-col-modules"></div>
          <div class="hld-col" id="hld-col-symbols"></div>
        </div>
        <div id="hld-detail" class="hld-detail"></div>
        <svg id="hld-focus" class="hld-focus" style="display:none"></svg>
      </div>
    </div>`;

  if (hldNav.layer && !(hld.components[hldNav.layer] || []).length) hldNav.layer = null;
  hldRenderNav();
  mermaid.run({ nodes: host.querySelectorAll('.mermaid') });
}

function hldRenderNav() {
  const hld = state.data.hld;
  const layers = hld.layers.filter(L => (hld.components[L.id] || []).length);

  const colLayers = document.getElementById('hld-col-layers');
  const colMods   = document.getElementById('hld-col-modules');
  const colSyms   = document.getElementById('hld-col-symbols');
  const crumb     = document.getElementById('hld-crumb');
  const detail    = document.getElementById('hld-detail');

  // ---- Layers column
  colLayers.innerHTML = `<div class="hld-col-h">Layers</div>` +
    layers.map(L => {
      const n = (hld.components[L.id] || []).length;
      const active = hldNav.layer === L.id ? ' active' : '';
      return `<div class="hld-row${active}" data-layer="${L.id}">
        <span class="swatch" style="background:${L.color}"></span>
        <div class="flex-1 min-w-0">
          <div class="hld-row-t">${esc(L.title)}</div>
          <div class="hld-row-s">${esc(L.subtitle)}</div>
        </div>
        <span class="pill">${n}</span>
        <i data-lucide="chevron-right" class="hld-chev"></i>
      </div>`;
    }).join('');
  colLayers.querySelectorAll('[data-layer]').forEach(el => {
    el.onclick = () => { hldNav.layer = el.dataset.layer;
      hldNav.module = null; hldNav.symbol = null; hldRenderNav(); };
  });

  // ---- Modules column
  if (!hldNav.layer) {
    colMods.innerHTML = `<div class="hld-col-h">Modules</div>
      <div class="hld-empty">Pick a layer →</div>`;
  } else {
    const modules = (hld.components[hldNav.layer] || [])
      .slice().sort((a, b) => b.symbols - a.symbols);
    colMods.innerHTML = `<div class="hld-col-h">Modules · ${esc(layerTitle(hldNav.layer))}</div>` +
      modules.map(c => {
        const active = hldNav.module === c.qualname ? ' active' : '';
        return `<div class="hld-row${active}" data-module="${esc(c.qualname)}">
          <i data-lucide="package" class="hld-ico"></i>
          <div class="flex-1 min-w-0">
            <div class="hld-row-t qn-mono">${formatQn(c.qualname, {maxParts: 2})}</div>
            <div class="hld-row-s">${esc(c.file || '')}</div>
          </div>
          <span class="pill">${c.symbols}</span>
          <i data-lucide="chevron-right" class="hld-chev"></i>
        </div>`;
      }).join('') || '<div class="hld-empty">No modules.</div>';
    colMods.querySelectorAll('[data-module]').forEach(el => {
      el.onclick = () => { hldNav.module = el.dataset.module;
        hldNav.symbol = null; hldRenderNav(); };
    });
  }

  // ---- Symbols column
  if (!hldNav.module) {
    colSyms.innerHTML = `<div class="hld-col-h">Symbols</div>
      <div class="hld-empty">Pick a module →</div>`;
  } else {
    const mod = (hld.modules || {})[hldNav.module];
    const symbols = mod ? (mod.symbols || []) : [];
    colSyms.innerHTML = `<div class="hld-col-h">Symbols · ${esc(shortQn(hldNav.module))}</div>` +
      (symbols.length
        ? symbols.map(s => {
            const active = hldNav.symbol === s.qualname ? ' active' : '';
            return `<div class="hld-row${active}" data-symbol="${esc(s.qualname)}">
              <i data-lucide="${kindIcon(s.kind)}" class="hld-ico" style="color:${kindColor(s.kind)}"></i>
              <div class="flex-1 min-w-0">
                <div class="hld-row-t qn-mono">${esc(s.name)}</div>
                <div class="hld-row-s">${s.kind} · L${s.line || '?'}</div>
              </div>
              <span class="pill" title="fan-in / fan-out">${s.fan_in}/${s.fan_out}</span>
            </div>`;
          }).join('')
        : '<div class="hld-empty">No symbols recorded.</div>');
    colSyms.querySelectorAll('[data-symbol]').forEach(el => {
      el.onclick = () => { hldNav.symbol = el.dataset.symbol; hldRenderNav(); };
    });
  }

  // ---- Crumb
  const parts = [];
  parts.push(`<a class="crumb-link" data-jump="root">All layers</a>`);
  if (hldNav.layer) parts.push(`<span class="crumb-sep">/</span>
    <a class="crumb-link" data-jump="layer">${esc(layerTitle(hldNav.layer))}</a>`);
  if (hldNav.module) parts.push(`<span class="crumb-sep">/</span>
    <a class="crumb-link qn-mono" data-jump="module">${esc(shortQn(hldNav.module))}</a>`);
  if (hldNav.symbol) parts.push(`<span class="crumb-sep">/</span>
    <span class="qn-mono">${esc(shortQn(hldNav.symbol))}</span>`);
  crumb.innerHTML = parts.join(' ');
  crumb.querySelectorAll('[data-jump]').forEach(el => {
    el.onclick = () => {
      if (el.dataset.jump === 'root') { hldNav.layer = hldNav.module = hldNav.symbol = null; }
      else if (el.dataset.jump === 'layer') { hldNav.module = hldNav.symbol = null; }
      else if (el.dataset.jump === 'module') { hldNav.symbol = null; }
      hldRenderNav();
    };
  });

  // ---- Detail panel + focus graph (only when a symbol is selected)
  const focus = document.getElementById('hld-focus');
  if (hldNav.symbol) {
    const mod = (hld.modules || {})[hldNav.module];
    const sym = mod && (mod.symbols || []).find(s => s.qualname === hldNav.symbol);
    if (sym) detail.innerHTML = symbolDetailHtml(sym, mod);
    detail.querySelectorAll('[data-jumpqn]').forEach(el => {
      el.onclick = () => jumpToQualname(el.dataset.jumpqn);
    });
    if (sym) drawFocusGraph(focus, sym);
  } else {
    detail.innerHTML = '';
    if (focus) { focus.style.display = 'none'; focus.innerHTML = ''; }
  }

  lucide.createIcons();
}

function symbolDetailHtml(sym, mod) {
  const callRow = qn => `<div class="call-row" data-jumpqn="${esc(qn)}">
    <i data-lucide="arrow-right" class="hld-ico"></i>
    <span class="qn-mono">${formatQn(qn, {maxParts: 3})}</span></div>`;
  const callerRow = qn => `<div class="call-row" data-jumpqn="${esc(qn)}">
    <i data-lucide="arrow-left" class="hld-ico"></i>
    <span class="qn-mono">${formatQn(qn, {maxParts: 3})}</span></div>`;

  return `
    <div class="hld-detail-head">
      <div class="flex items-start gap-3 min-w-0 flex-1">
        <i data-lucide="${kindIcon(sym.kind)}" class="hld-ico" style="color:${kindColor(sym.kind)};margin-top:6px"></i>
        <div class="min-w-0">
          <div class="hld-detail-title qn-mono">${formatQn(sym.qualname, {maxParts: 5})}</div>
          <div class="hld-detail-meta">
            <span class="pill">${sym.kind}</span>
            <span class="pill">L${sym.line || '?'}</span>
            <span class="pill pill-cool" title="fan-in">in: ${sym.fan_in}</span>
            <span class="pill pill-warm" title="fan-out">out: ${sym.fan_out}</span>
            <span class="text-[11px] text-app-2">${esc(mod ? mod.file : '')}</span>
          </div>
        </div>
      </div>
    </div>
    <div class="grid grid-cols-1 md:grid-cols-2 gap-4 mt-3">
      <div>
        <div class="hld-col-h flex items-center gap-1.5"><i data-lucide="arrow-left" class="w-3.5 h-3.5"></i>Called by (${sym.fan_in})</div>
        ${(sym.callers && sym.callers.length)
          ? sym.callers.map(callerRow).join('')
          : '<div class="hld-empty">No callers in graph.</div>'}
      </div>
      <div>
        <div class="hld-col-h flex items-center gap-1.5"><i data-lucide="arrow-right" class="w-3.5 h-3.5"></i>Calls (${sym.fan_out})</div>
        ${(sym.callees && sym.callees.length)
          ? sym.callees.map(callRow).join('')
          : '<div class="hld-empty">Calls nothing tracked.</div>'}
      </div>
    </div>`;
}

function jumpToQualname(qn) {
  // Find the module that owns this qualname (longest prefix match) and select it.
  const mods = (state.data.hld.modules || {});
  const candidates = Object.keys(mods).filter(mq => qn === mq || qn.startsWith(mq + '.'));
  if (!candidates.length) return;
  const mqn = candidates.sort((a, b) => b.length - a.length)[0];
  const mod = mods[mqn];
  hldNav.layer = mod.layer;
  hldNav.module = mqn;
  hldNav.symbol = (mod.symbols || []).some(s => s.qualname === qn) ? qn : null;
  hldRenderNav();
}

function layerTitle(id) {
  const L = (state.data.hld.layers || []).find(x => x.id === id);
  return L ? L.title : id;
}
function kindIcon(k) {
  return k === 'CLASS' ? 'box' : k === 'METHOD' ? 'corner-down-right' : 'function-square';
}
function kindColor(k) {
  return k === 'CLASS' ? 'var(--accent-violet)'
       : k === 'METHOD' ? 'var(--accent-cyan)'
       : 'var(--accent-emerald)';
}

/* Radial focus graph for the selected symbol. Center = symbol; left arc =
   callers; right arc = callees. Edges are dashed and animated (CSS) to give
   a sense of data flowing inward / outward. Click any node to jump. */
function drawFocusGraph(svg, sym) {
  if (!svg) return;
  const callers = (sym.callers || []).slice(0, 8);
  const callees = (sym.callees || []).slice(0, 8);
  if (!callers.length && !callees.length) {
    svg.style.display = 'none'; svg.innerHTML = ''; return;
  }
  svg.style.display = 'block';
  d3.select(svg).selectAll('*').remove();

  const W = svg.parentElement.clientWidth - 4;
  const H = 320;
  svg.setAttribute('viewBox', `0 0 ${W} ${H}`);
  svg.setAttribute('preserveAspectRatio', 'xMidYMid meet');
  svg.setAttribute('width', W); svg.setAttribute('height', H);

  const cx = W / 2, cy = H / 2;
  const R = Math.min(H * 0.42, W * 0.32);

  const arcPositions = (n, side) => {
    if (n === 0) return [];
    const span = Math.min(Math.PI * 0.85, 0.5 + n * 0.18);
    const start = side === 'left' ? Math.PI - span / 2 : -span / 2;
    return d3.range(n).map(i => {
      const t = n === 1 ? 0.5 : i / (n - 1);
      const a = start + t * span;
      return [cx + R * Math.cos(a), cy + R * Math.sin(a)];
    });
  };

  const left  = arcPositions(callers.length, 'left');
  const right = arcPositions(callees.length, 'right');

  const root = d3.select(svg);
  const g = root.append('g');

  // Edges (callers → center, center → callees). dashoffset CSS animation.
  callers.forEach((qn, i) => {
    const [x, y] = left[i];
    g.append('path')
      .attr('class', 'focus-edge focus-in')
      .attr('d', `M${x},${y} Q${(x+cx)/2},${(y+cy)/2 - 18} ${cx},${cy}`);
  });
  callees.forEach((qn, i) => {
    const [x, y] = right[i];
    g.append('path')
      .attr('class', 'focus-edge focus-out')
      .attr('d', `M${cx},${cy} Q${(cx+x)/2},${(cy+y)/2 - 18} ${x},${y}`);
  });

  // Caller / callee nodes.
  const node = (qn, x, y, side) => {
    const grp = g.append('g')
      .attr('class', 'focus-node')
      .attr('transform', `translate(${x},${y})`)
      .style('cursor', 'pointer')
      .on('click', () => jumpToQualname(qn));
    grp.append('circle').attr('r', 8)
       .attr('class', side === 'in' ? 'focus-dot focus-dot-in' : 'focus-dot focus-dot-out');
    const label = shortQn(qn);
    grp.append('text')
       .attr('y', 22).attr('text-anchor', 'middle')
       .attr('class', 'focus-label')
       .text(label.length > 26 ? label.slice(0, 25) + '…' : label);
  };
  callers.forEach((qn, i) => node(qn, left[i][0], left[i][1], 'in'));
  callees.forEach((qn, i) => node(qn, right[i][0], right[i][1], 'out'));

  // Center node.
  const center = g.append('g').attr('transform', `translate(${cx},${cy})`);
  center.append('circle').attr('r', 22).attr('class', 'focus-core');
  center.append('circle').attr('r', 28).attr('class', 'focus-core-ring');
  center.append('text').attr('y', 5).attr('text-anchor', 'middle')
        .attr('class', 'focus-core-label')
        .text(shortQn(sym.qualname).slice(0, 18));

  // Side captions.
  if (callers.length) {
    g.append('text').attr('x', 16).attr('y', 22)
     .attr('class', 'focus-caption')
     .text(`called by · ${sym.fan_in}`);
  }
  if (callees.length) {
    g.append('text').attr('x', W - 16).attr('y', 22)
     .attr('text-anchor', 'end')
     .attr('class', 'focus-caption')
     .text(`calls · ${sym.fan_out}`);
  }
}

// ---------- Flows ----------
function renderFlows(host) {
  const flows = state.data.flows;
  if (!flows.length) {
    host.innerHTML = `<div class="p-8 text-ink-200">No call chains found.</div>`;
    return;
  }
  if (state.flowSel >= flows.length) state.flowSel = 0;
  host.innerHTML = `
    <div class="p-8 max-w-7xl mx-auto">
      <div class="help-card mb-6">
        <i data-lucide="git-fork" class="icon w-4 h-4"></i>
        <div><b>Call flow inspector.</b> Pick an entry point on the left to see its real downstream call tree (BFS depth 4).
        Highlighted node = entry; arrows = CALLS edges from the actual graph.</div>
      </div>
      <div class="grid grid-cols-[300px_1fr] gap-4">
        <div class="panel p-3 max-h-[78vh] overflow-y-auto">
          <div class="search-wrap mb-3">
            <i data-lucide="search"></i>
            <input class="search" id="flow-search" placeholder="Filter entry points…">
          </div>
          <div id="flow-list" class="space-y-1"></div>
        </div>
        <div class="panel p-5 min-h-[600px]">
          <div class="section-h"><h2 id="flow-title">Flow</h2>
            <span class="pill" id="flow-meta"></span></div>
          <div class="mermaid-host" id="flow-canvas"></div>
        </div>
      </div>
    </div>`;
  const list = document.getElementById('flow-list');
  flows.forEach((f, i) => {
    const el = document.createElement('div');
    el.className = 'flow-item';
    el.innerHTML = `<div class="qn">${formatQn(f.qualname, {maxParts: 3})}</div>
      <div class="meta"><i data-lucide="zap" style="width:11px;height:11px"></i>
      ${esc(f.reason)} <span class="text-ink-300">· ${esc(f.file)}</span></div>`;
    el.onclick = () => selectFlow(i);
    list.appendChild(el);
  });
  document.getElementById('flow-search').addEventListener('input', e => {
    const q = e.target.value.toLowerCase();
    [...list.children].forEach((el, i) => {
      el.style.display = JSON.stringify(flows[i]).toLowerCase().includes(q) ? '' : 'none';
    });
  });
  selectFlow(state.flowSel);
}
function shortQn(qn) {
  const parts = String(qn).split('.');
  return parts.length > 3 ? '…' + parts.slice(-3).join('.') : qn;
}

/* HTML version of shortQn that dims the parent path and highlights the leaf.
   Returns sanitized markup. */
function formatQn(qn, opts) {
  const max = (opts && opts.maxParts) || 3;
  const parts = String(qn ?? '').split('.');
  if (!parts.length) return '';
  const leaf = parts[parts.length - 1];
  const headParts = parts.slice(0, -1);
  const truncated = headParts.length > max - 1;
  const visibleHead = truncated ? headParts.slice(-(max - 1)) : headParts;
  const prefix = truncated ? '…' : '';
  const head = visibleHead.length
    ? `<span class="qn-dim">${prefix}${esc(visibleHead.join('.'))}.</span>`
    : (truncated ? `<span class="qn-dim">${prefix}</span>` : '');
  return `${head}<span class="qn-key">${esc(leaf)}</span>`;
}
function selectFlow(i) {
  state.flowSel = i;
  const flow = state.data.flows[i];
  if (!flow) return;
  document.querySelectorAll('.flow-item').forEach((el, j) =>
    el.classList.toggle('active', j === i));
  document.getElementById('flow-title').innerHTML = formatQn(flow.qualname, {maxParts: 4});
  document.getElementById('flow-title').classList.add('qn-mono');
  document.getElementById('flow-meta').textContent = flow.reason;
  const canvas = document.getElementById('flow-canvas');
  canvas.innerHTML = `<pre class="mermaid">${esc(flow.mermaid)}</pre>`;
  mermaid.run({ nodes: canvas.querySelectorAll('.mermaid') });
}

// ---------- Matrix ----------
function renderMatrix(host) {
  const m = state.data.matrix;
  if (!m.modules.length) {
    host.innerHTML = `<div class="p-8 text-ink-200">No cross-module CALLS recorded.</div>`;
    return;
  }
  const max = m.max || 1;
  const colour = v => {
    if (!v) return 'transparent';
    const t = v / max;
    // Cool indigo -> violet -> warm rose for heat.
    const stops = [
      [42,  57,  87],   // ink-500
      [99,  102, 241],  // brand-600
      [167, 139, 250],  // accent-violet
      [248, 113, 113],  // accent-rose
    ];
    const seg = Math.min(stops.length - 2, Math.floor(t * (stops.length - 1)));
    const lt  = (t * (stops.length - 1)) - seg;
    const a = stops[seg], b = stops[seg + 1];
    const r = Math.round(a[0] + lt * (b[0] - a[0]));
    const g = Math.round(a[1] + lt * (b[1] - a[1]));
    const bl= Math.round(a[2] + lt * (b[2] - a[2]));
    return `rgb(${r},${g},${bl})`;
  };
  let html = `<div class="p-8 max-w-7xl mx-auto">
    <div class="help-card mb-6">
      <i data-lucide="grid-3x3" class="icon w-4 h-4"></i>
      <div><b>Module call matrix.</b> Each row is a caller, each column a callee. Cell color and number = number of calls.
      Rotate your head 45° to read column labels - or hover any cell for the exact pair.</div>
    </div>
    <div class="panel p-4">
      <div class="matrix-wrap"><table class="matrix"><thead><tr><th class="corner"></th>`;
  m.modules.forEach(mod => {
    html += `<th title="${esc(mod.qualname)}">${esc(mod.name)}</th>`;
  });
  html += `</tr></thead><tbody>`;
  m.modules.forEach((row, i) => {
    html += `<tr><th title="${esc(row.qualname)}">${esc(row.qualname)}</th>`;
    m.counts[i].forEach((v, j) => {
      const tip = v ? `<b>${esc(row.name)}</b> -> <b>${esc(m.modules[j].name)}</b><br>${v} call${v===1?'':'s'}` : '';
      html += `<td class="cell" data-tip="${tip}" style="background:${colour(v)}">${v || ''}</td>`;
    });
    html += `</tr>`;
  });
  html += `</tbody></table></div>
    <div class="flex items-center gap-3 mt-4 text-[11px] text-ink-200">
      <span>0</span>
      <div class="h-2.5 w-48 rounded-full" style="background:linear-gradient(90deg,#2a3957,#6366f1,#a78bfa,#f87171)"></div>
      <span class="font-mono">${max}</span>
    </div></div></div>`;
  host.innerHTML = html;
  host.querySelectorAll('td.cell').forEach(c => {
    c.addEventListener('mousemove', e => {
      const t = e.target.dataset.tip;
      if (t) showTip(t, e.clientX, e.clientY);
    });
    c.addEventListener('mouseleave', hideTip);
  });
}

// ---------- Sankey ----------
function renderSankey(host) {
  const data = state.data.sankey;
  host.innerHTML = `<div class="p-8 max-w-7xl mx-auto">
    <div class="help-card mb-6">
      <i data-lucide="waves" class="icon w-4 h-4"></i>
      <div><b>Inter-module call flows.</b> Width of each ribbon = number of calls between two modules.
      Hover anything for exact counts.</div>
    </div>
    <div class="panel p-5">
      <div class="section-h"><h2>Top call flows</h2><span class="text-[11px] text-ink-200">${data.links.length} flows</span></div>
      ${data.links.length ? '<svg id="sankey" class="w-full" style="height:680px"></svg>'
                          : '<div class="text-ink-200 p-12 text-center">No cross-module flows yet.</div>'}
    </div></div>`;
  if (!data.links.length) return;
  const svg = d3.select('#sankey');
  const { width, height } = svg.node().getBoundingClientRect();
  const sk = d3.sankey().nodeWidth(14).nodePadding(10)
    .extent([[6, 6], [width - 6, height - 6]]);
  const g = sk({
    nodes: data.nodes.map(d => ({...d})),
    links: data.links.map(d => ({...d})),
  });
  const colour = d3.scaleOrdinal()
    .range(['#818cf8','#22d3ee','#34d399','#fbbf24','#f87171','#a78bfa','#fb923c']);
  svg.append('g').selectAll('rect').data(g.nodes).join('rect')
    .attr('x', d => d.x0).attr('y', d => d.y0)
    .attr('height', d => d.y1 - d.y0).attr('width', d => d.x1 - d.x0)
    .attr('fill', d => colour(d.package || d.name))
    .attr('rx', 2)
    .on('mousemove', (e, d) => showTip(`<b>${esc(d.qualname)}</b><br>value: ${Math.round(d.value)}`, e.clientX, e.clientY))
    .on('mouseleave', hideTip);
  svg.append('g').attr('fill', 'none').selectAll('path').data(g.links).join('path')
    .attr('d', d3.sankeyLinkHorizontal())
    .attr('stroke', d => colour(d.source.package || d.source.name))
    .attr('stroke-width', d => Math.max(1, d.width))
    .attr('stroke-opacity', 0.4)
    .on('mousemove', (e, d) => showTip(
      `${esc(d.source.qualname)} → ${esc(d.target.qualname)}<br>${d.value} call(s)`,
      e.clientX, e.clientY))
    .on('mouseleave', hideTip);
  svg.append('g').attr('class', 'd3-label').selectAll('text').data(g.nodes).join('text')
    .attr('x', d => d.x0 < width / 2 ? d.x1 + 8 : d.x0 - 8)
    .attr('y', d => (d.y1 + d.y0) / 2).attr('dy', '0.35em')
    .attr('text-anchor', d => d.x0 < width / 2 ? 'start' : 'end')
    .text(d => d.name);
}

// ---------- Treemap ----------
function renderTreemap(host) {
  host.innerHTML = `<div class="p-8 max-w-7xl mx-auto">
    <div class="help-card mb-6">
      <i data-lucide="square-stack" class="icon w-4 h-4"></i>
      <div><b>Codebase footprint.</b> Each rectangle = one module. Area = LOC; brighter color = higher hotspot score.
      Hover any cell for full details.</div>
    </div>
    <div class="panel p-5">
      <div class="section-h"><h2>LOC landscape</h2></div>
      <svg id="treemap" class="w-full" style="height:720px"></svg>
    </div></div>`;
  const root = d3.hierarchy(state.data.treemap)
    .sum(d => d.value || 0).sort((a, b) => b.value - a.value);
  const svg = d3.select('#treemap');
  const { width, height } = svg.node().getBoundingClientRect();
  d3.treemap().size([width, height]).paddingInner(3).paddingTop(22).round(true)(root);
  const maxScore = d3.max(root.leaves(), d => d.data.score) || 1;
  const colour = d3.scaleSequential([0, maxScore], d3.interpolateInferno);

  const pkg = svg.append('g').selectAll('g')
    .data(root.descendants().filter(d => d.depth === 1))
    .join('g').attr('transform', d => `translate(${d.x0},${d.y0})`);
  pkg.append('rect').attr('width', d => d.x1 - d.x0).attr('height', d => d.y1 - d.y0)
    .attr('fill', '#131c2e').attr('stroke', '#243049').attr('rx', 4);
  pkg.append('text').attr('x', 8).attr('y', 14).attr('fill', '#cbd5e1')
    .style('font-size', '11px').style('font-weight', '600').text(d => d.data.name);

  const leaf = svg.append('g').selectAll('g').data(root.leaves())
    .join('g').attr('transform', d => `translate(${d.x0},${d.y0})`);
  leaf.append('rect').attr('width', d => Math.max(0, d.x1 - d.x0))
    .attr('height', d => Math.max(0, d.y1 - d.y0))
    .attr('fill', d => d.data.score ? colour(d.data.score) : '#243049')
    .attr('stroke', '#0b1220').attr('stroke-width', 1).attr('rx', 2)
    .style('cursor', 'pointer')
    .on('mousemove', (e, d) => showTip(
       `<b>${esc(d.data.name)}</b><br>${esc(d.data.file)}<br>` +
       `LOC: ${d.data.value} · symbols: ${d.data.symbols} · score: ${d.data.score}`,
       e.clientX, e.clientY))
    .on('mouseleave', hideTip);
  leaf.append('text').attr('x', 6).attr('y', 14).attr('fill', '#fff')
    .style('font-size', '10.5px').style('font-weight', '500')
    .style('pointer-events', 'none')
    .text(d => {
      const w = d.x1 - d.x0, h = d.y1 - d.y0;
      if (w < 60 || h < 22) return '';
      const name = d.data.name.split('.').pop();
      return name.length * 6 > w - 12 ? name.slice(0, Math.floor((w-12)/6)) + '…' : name;
    });
}

// ---------- Architecture (links to pyvis) ----------
function pyvisHref(path) {
  const t = document.documentElement.classList.contains('theme-light') ? 'light' : 'dark';
  return path + '?theme=' + t;
}

function renderArchitecture(host) {
  const tile = (href, title, desc, icon) => `
    <a href="${href}" target="_blank" rel="noopener" class="panel p-5 block hover:border-brand-500 transition group">
      <div class="flex items-start gap-3">
        <div class="w-10 h-10 rounded-lg bg-app-3 flex items-center justify-center text-brand-500 group-hover:bg-brand-600 group-hover:text-white transition">
          <i data-lucide="${icon}" class="w-5 h-5"></i>
        </div>
        <div>
          <div class="font-semibold text-[15px]">${title}</div>
          <div class="text-[12px] text-app-2 mt-1 leading-relaxed">${desc}</div>
        </div>
      </div>
    </a>`;
  host.innerHTML = `<div class="p-8 max-w-6xl mx-auto">
    <div class="help-card mb-6">
      <i data-lucide="compass" class="icon w-4 h-4"></i>
      <div><b>Interactive node-link explorers.</b> Force-directed graphs powered by pyvis with in-page search and filtering. Best for hands-on exploration.</div>
    </div>
    <div class="grid grid-cols-1 md:grid-cols-3 gap-4">
      ${tile(pyvisHref('/architecture.html'), 'Architecture', 'One node per module, edges aggregated by kind. Best high-level node-link view.', 'network')}
      ${tile(pyvisHref('/callgraph.html'), 'Call graph', 'Every function and method, sized by fan-in. Use the filter menu to narrow.', 'workflow')}
      ${tile(pyvisHref('/inheritance.html'), 'Inheritance', 'Classes only. INHERITS / IMPLEMENTS edges drawn.', 'git-branch')}
    </div></div>`;
}

// ---------- Files ----------
function renderFiles(host) {
  const files = state.data.files;
  const rows = files.map(f => {
    const slug = f.file.replace(/[^a-zA-Z0-9_-]+/g, '_').replace(/^_|_$/g, '') || 'file';
    return `<tr>
      <td><a class="link" href="${pyvisHref('/files/' + slug + '.html')}" target="_blank" rel="noopener"><code>${esc(f.file)}</code></a></td>
      <td class="text-app-2">${esc(f.language)}</td>
      <td class="num"><span class="pill">${f.symbols}</span></td>
    </tr>`;
  }).join('');
  host.innerHTML = `<div class="p-8 max-w-6xl mx-auto">
    <div class="help-card mb-6">
      <i data-lucide="folder-tree" class="icon w-4 h-4"></i>
      <div><b>Per-file pyvis pages.</b> Click any file to see its symbols + 1-hop neighbours.</div>
    </div>
    <div class="panel p-5">
      <div class="section-h"><h2>Files (${files.length})</h2></div>
      <table class="data"><thead><tr><th>Path</th><th>Language</th><th class="num">Symbols</th></tr></thead>
      <tbody>${rows}</tbody></table>
    </div></div>`;
}

// ---------- esc ----------
function esc(s) {
  return String(s ?? '').replace(/[&<>"']/g, c =>
    ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}

// ---------- Bootstrap ----------
async function load() {
  const r = await fetch('/api/data.json');
  state.data = await r.json();
  document.getElementById('repo-name').textContent = state.data.repo || 'graph';
  document.getElementById('last-built').textContent = state.data.built_at
    ? 'built ' + state.data.built_at : '';
  setHeaderStats();
  buildNav();
  const hash = (location.hash || '#overview').slice(1);
  activate(VIEWS.find(v => v.id === hash) ? hash : 'overview');
}

document.getElementById('sb-toggle').addEventListener('click', () => {
  const collapsed = document.documentElement.classList.toggle('sb-collapsed');
  try { localStorage.setItem('cg-sb', collapsed ? 'collapsed' : 'expanded'); } catch (e) {}
});

document.getElementById('theme-toggle').addEventListener('click', () => {
  const light = document.documentElement.classList.toggle('theme-light');
  try { localStorage.setItem('cg-theme', light ? 'light' : 'dark'); } catch (e) {}
  // Re-init mermaid with new theme + re-render current view so SVGs redraw.
  initMermaid();
  if (state.data) render(state.view);
});

document.getElementById('rebuild-btn').addEventListener('click', async (e) => {
  const btn = e.currentTarget;
  btn.disabled = true;
  btn.innerHTML = '<div class="spinner"></div><span>Rebuilding…</span>';
  try {
    const r = await fetch('/api/rebuild', { method: 'POST' });
    if (!r.ok) throw new Error('rebuild failed');
    await load();
    render(state.view);
    toast('Rebuilt', 'success');
  } catch (err) {
    toast('Rebuild failed: ' + err.message, 'error');
  } finally {
    btn.disabled = false;
    btn.innerHTML = '<i data-lucide="refresh-cw" class="w-3.5 h-3.5"></i><span>Rebuild</span>';
    lucide.createIcons();
  }
});

load().catch(err => {
  document.getElementById('view-host').innerHTML =
    `<div class="p-8"><div class="help-card"><i data-lucide="alert-triangle" class="icon w-4 h-4"></i>
    <div><b>Failed to load data.</b> ${esc(err.message)}</div></div></div>`;
  lucide.createIcons();
});
