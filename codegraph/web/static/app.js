/* codegraph dashboard - vanilla JS app */
'use strict';

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
mermaid.initialize({
  startOnLoad: false, theme: 'dark',
  themeVariables: {
    fontFamily: 'Inter, system-ui, sans-serif', fontSize: '14px',
    primaryColor: '#1a2540', primaryTextColor: '#e2e8f0',
    primaryBorderColor: '#243049', lineColor: '#475569',
    secondaryColor: '#131c2e', tertiaryColor: '#0f172a',
    clusterBkg: '#0f172a', clusterBorder: '#243049',
    nodeBorder: '#243049', mainBkg: '#1a2540',
  },
  flowchart: { padding: 16, nodeSpacing: 36, rankSpacing: 50,
               curve: 'basis', htmlLabels: true, useMaxWidth: true },
});

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
      <td><code>${esc(h.qualname)}</code></td>
      <td class="text-ink-200">${esc(h.file)}</td>
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
function renderHld(host) {
  const hld = state.data.hld;
  if (!hld) { host.innerHTML = '<div class="p-8 text-ink-200">No HLD payload.</div>'; return; }
  const m = hld.metrics;
  const card = (n, l) => `
    <div class="stat-card"><div class="stat-num">${n}</div>
    <div class="stat-lbl">${l}</div></div>`;
  const layerRow = L => {
    const c = (hld.components[L.id] || []).length;
    return `<div class="flex items-center gap-3 p-2 rounded-md hover:bg-ink-700">
      <div class="swatch" style="background:${L.color}"></div>
      <div class="flex-1 min-w-0">
        <div class="text-[13px] font-medium text-ink-50">${esc(L.title)}</div>
        <div class="text-[11px] text-ink-200 truncate">${c} module${c===1?'':'s'} - ${esc(L.subtitle)}</div>
      </div>
      <span class="pill">${c}</span>
    </div>`;
  };
  const edgeRow = e => {
    const sl = hld.layers.find(L => L.id === e.source) || {title: e.source};
    const tl = hld.layers.find(L => L.id === e.target) || {title: e.target};
    return `<tr><td>${esc(sl.title)}</td>
      <td class="text-ink-200 text-center">→</td>
      <td>${esc(tl.title)}</td>
      <td class="num"><span class="pill ${e.kind==='CALLS'?'pill-cool':''}">${e.weight}</span></td>
      <td class="text-ink-200 text-[11px] uppercase tracking-wider">${e.kind}</td></tr>`;
  };

  host.innerHTML = `
    <div class="p-8 space-y-6 max-w-7xl mx-auto">
      <div class="help-card">
        <i data-lucide="map" class="icon w-4 h-4"></i>
        <div><b>How to read this.</b> Top diagram = system context (the world the CLI lives in).
        Below = layered architecture: each colored band is a layer of the codebase, each box inside is a Python module
        (label = name, badge = symbol count). Arrow labels show real call/import counts crossing layer boundaries; thicker arrows = heavier traffic.</div>
      </div>
      <div class="grid grid-cols-2 md:grid-cols-4 gap-3">
        ${card(m.layers, 'Layers')}
        ${card(m.components, 'Modules')}
        ${card(m.cross_layer_edges, 'Cross-layer edges')}
        ${card(m.total_cross_layer_calls, 'Cross-layer calls')}
      </div>
      <div class="grid grid-cols-1 lg:grid-cols-[1fr_320px] gap-4">
        <div class="space-y-4 min-w-0">
          <div class="panel p-5">
            <div class="section-h"><h2>System context</h2>
              <span class="text-[11px] text-ink-200">C4-style</span></div>
            <div class="mermaid-host"><pre class="mermaid">${esc(hld.mermaid_context)}</pre></div>
          </div>
          <div class="panel p-5">
            <div class="section-h"><h2>Layered architecture</h2>
              <span class="text-[11px] text-ink-200">live data</span></div>
            <div class="mermaid-host"><pre class="mermaid">${esc(hld.mermaid_layered)}</pre></div>
          </div>
        </div>
        <div class="space-y-4">
          <div class="panel p-5">
            <div class="section-h"><h2>Layers</h2></div>
            <div class="space-y-1">${hld.layers.filter(L=>(hld.components[L.id]||[]).length).map(layerRow).join('')}</div>
          </div>
          <div class="panel p-5">
            <div class="section-h"><h2>Top cross-layer flows</h2></div>
            <table class="data">
              <thead><tr><th>From</th><th></th><th>To</th><th class="num">Wt</th><th>Kind</th></tr></thead>
              <tbody>${hld.edges.slice(0, 18).map(edgeRow).join('') || '<tr><td colspan="5" class="text-ink-200">none</td></tr>'}</tbody>
            </table>
          </div>
        </div>
      </div>
    </div>`;
  mermaid.run({ nodes: host.querySelectorAll('.mermaid') });
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
            <input class="search" id="flow-search" placeholder="Filter entry points...">
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
    el.innerHTML = `<div class="qn">${esc(shortQn(f.qualname))}</div>
      <div class="meta"><i data-lucide="zap" style="width:11px;height:11px"></i>
      ${esc(f.reason)} <span class="text-ink-300">- ${esc(f.file)}</span></div>`;
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
  const parts = qn.split('.');
  return parts.length > 3 ? '...' + parts.slice(-3).join('.') : qn;
}
function selectFlow(i) {
  state.flowSel = i;
  const flow = state.data.flows[i];
  if (!flow) return;
  document.querySelectorAll('.flow-item').forEach((el, j) =>
    el.classList.toggle('active', j === i));
  document.getElementById('flow-title').textContent = shortQn(flow.qualname);
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
    const r = Math.round(36 + t * (251 - 36));
    const g = Math.round(48 + t * (113 - 48));
    const b = Math.round(80 + t * (133 - 80));
    return `rgb(${r},${g},${b})`;
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
      <div class="h-2.5 w-48 rounded-full" style="background:linear-gradient(90deg,#243049,#6366f1,#fb7185)"></div>
      <span>${max}</span>
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
    .range(['#818cf8','#22d3ee','#34d399','#fcd34d','#fb7185','#a78bfa','#fb923c']);
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
       `LOC: ${d.data.value} - symbols: ${d.data.symbols} - score: ${d.data.score}`,
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
function renderArchitecture(host) {
  const tile = (href, title, desc, icon) => `
    <a href="${href}" class="panel p-5 block hover:border-brand-500 transition group">
      <div class="flex items-start gap-3">
        <div class="w-10 h-10 rounded-lg bg-ink-700 flex items-center justify-center text-brand-500 group-hover:bg-brand-600 group-hover:text-white transition">
          <i data-lucide="${icon}" class="w-5 h-5"></i>
        </div>
        <div>
          <div class="font-semibold text-[15px]">${title}</div>
          <div class="text-[12px] text-ink-200 mt-1 leading-relaxed">${desc}</div>
        </div>
      </div>
    </a>`;
  host.innerHTML = `<div class="p-8 max-w-6xl mx-auto">
    <div class="help-card mb-6">
      <i data-lucide="compass" class="icon w-4 h-4"></i>
      <div><b>Interactive node-link explorers.</b> Force-directed graphs powered by pyvis with in-page search and filtering. Best for hands-on exploration.</div>
    </div>
    <div class="grid grid-cols-1 md:grid-cols-3 gap-4">
      ${tile('/architecture.html', 'Architecture', 'One node per module, edges aggregated by kind. Best high-level node-link view.', 'network')}
      ${tile('/callgraph.html', 'Call graph', 'Every function and method, sized by fan-in. Use the filter menu to narrow.', 'workflow')}
      ${tile('/inheritance.html', 'Inheritance', 'Classes only. INHERITS / IMPLEMENTS edges drawn.', 'git-branch')}
    </div></div>`;
}

// ---------- Files ----------
function renderFiles(host) {
  const files = state.data.files;
  const rows = files.map(f => {
    const slug = f.file.replace(/[^a-zA-Z0-9_-]+/g, '_').replace(/^_|_$/g, '') || 'file';
    return `<tr>
      <td><a class="link" href="/files/${slug}.html"><code>${esc(f.file)}</code></a></td>
      <td class="text-ink-200">${esc(f.language)}</td>
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
  document.getElementById('last-built').textContent = 'built ' + (state.data.built_at || '');
  setHeaderStats();
  buildNav();
  const hash = (location.hash || '#overview').slice(1);
  activate(VIEWS.find(v => v.id === hash) ? hash : 'overview');
}

document.getElementById('rebuild-btn').addEventListener('click', async (e) => {
  const btn = e.currentTarget;
  btn.disabled = true;
  btn.innerHTML = '<div class="spinner"></div><span>Rebuilding...</span>';
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
