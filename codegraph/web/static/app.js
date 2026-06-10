/* codegraph dashboard - app shell */
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
// Expose to other view scripts (graph3d.js etc.) that load in separate
// <script> tags. Top-level `const` is not implicitly a window property.
window.state = state;

const VIEWS = [
  { section: 'Insights' },
  { id: 'overview',     label: 'Overview',     icon: 'layout-dashboard' },
  { id: 'hld',          label: 'HLD',          icon: 'layers' },
  { id: 'architecture', label: 'Architecture', icon: 'cloud' },
  { id: 'flows',        label: 'Call flows',   icon: 'git-fork' },
  { section: 'Diagrams' },
  { id: 'matrix',       label: 'Matrix',       icon: 'grid-3x3' },
  { id: 'sankey',       label: 'Sankey',       icon: 'waves' },
  { id: 'treemap',      label: 'Treemap',      icon: 'square-stack' },
  { id: 'graph3d',      label: '3D Graph',     icon: 'atom' },
  { section: 'Browse' },
  { id: 'explorers',    label: 'Explorers',    icon: 'compass' },
  { id: 'files',        label: 'Files',        icon: 'folder-tree' },
];

// ---- Mermaid init ----
function initMermaid() {
  mermaid.initialize({
    startOnLoad: false, theme: 'base',
    themeVariables: CGUI.mermaidThemeVars(),
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
  overview:     host => CGViews.overview(host),
  hld:          host => CGViews.hld(host),
  flows:        host => CGViews.flows(host),
  matrix:       host => CGViews.matrix(host),
  sankey:       host => CGViews.sankey(host),
  treemap:      host => CGViews.treemap(host),
  graph3d:      host => renderGraph3dShim(host),
  architecture: host => {
    if (typeof window.renderArchitectureView === 'function') {
      window.renderArchitectureView(host);
    } else {
      host.innerHTML = '<div class="p-8 text-ink-200">Architecture view not loaded.</div>';
    }
  },
  explorers:    host => CGViews.explorers(host),
  files:        host => CGViews.files(host),
};

// ---------- Graph3D shim ----------
// Delegates to window.renderGraph3d (defined in views/graph3d.js). Kept as a
// named function so VIEW_RENDERERS can reference it without a hoist trap.
function renderGraph3dShim(host) {
  if (typeof window.renderGraph3d === 'function') return window.renderGraph3d(host);
  const msg = document.createElement('div');
  msg.className = 'p-8 text-ink-200';
  msg.textContent = '3D view module failed to load.';
  host.appendChild(msg);
}

// ---------- Explorers + Files (small, stay in shell) ----------
function renderExplorers(host) {
  const esc = CGUI.esc;
  const pyvisHref = CGUI.pyvisHref;
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

function renderFiles(host) {
  const esc = CGUI.esc;
  const pyvisHref = CGUI.pyvisHref;
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

// Wire explorers + files into CGViews so VIEW_RENDERERS dispatch is uniform.
CGViews.explorers = renderExplorers;
CGViews.files = renderFiles;

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
    CGUI.toast('Rebuilt', 'success');
  } catch (err) {
    CGUI.toast('Rebuild failed: ' + err.message, 'error');
  } finally {
    btn.disabled = false;
    btn.innerHTML = '<i data-lucide="refresh-cw" class="w-3.5 h-3.5"></i><span>Rebuild</span>';
    lucide.createIcons();
  }
});

load().catch(err => {
  document.getElementById('view-host').innerHTML =
    `<div class="p-8"><div class="help-card"><i data-lucide="alert-triangle" class="icon w-4 h-4"></i>
    <div><b>Failed to load data.</b> ${CGUI.esc(err.message)}</div></div></div>`;
  lucide.createIcons();
});
