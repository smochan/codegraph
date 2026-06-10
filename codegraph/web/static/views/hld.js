/* codegraph dashboard - HLD view */
'use strict';

// Module-local nav state (persists across re-renders within session).
const _hldNav = { layer: null, module: null, symbol: null };

CGViews.hld = function renderHld(host) {
  const esc = CGUI.esc;
  const hld = window.state.data.hld;
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

  if (_hldNav.layer && !(hld.components[_hldNav.layer] || []).length) _hldNav.layer = null;
  _hldRenderNav();
  mermaid.run({ nodes: host.querySelectorAll('.mermaid') });
};

function _hldRenderNav() {
  const esc = CGUI.esc;
  const formatQn = CGUI.formatQn;
  const kindIcon = CGUI.kindIcon;
  const kindColor = CGUI.kindColor;
  const hld = window.state.data.hld;
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
      const active = _hldNav.layer === L.id ? ' active' : '';
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
    el.onclick = () => { _hldNav.layer = el.dataset.layer;
      _hldNav.module = null; _hldNav.symbol = null; _hldRenderNav(); };
  });

  // ---- Modules column
  if (!_hldNav.layer) {
    colMods.innerHTML = `<div class="hld-col-h">Modules</div>
      <div class="hld-empty">Pick a layer →</div>`;
  } else {
    const modules = (hld.components[_hldNav.layer] || [])
      .slice().sort((a, b) => b.symbols - a.symbols);
    colMods.innerHTML = `<div class="hld-col-h">Modules · ${esc(_hldLayerTitle(_hldNav.layer))}</div>` +
      modules.map(c => {
        const active = _hldNav.module === c.qualname ? ' active' : '';
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
      el.onclick = () => { _hldNav.module = el.dataset.module;
        _hldNav.symbol = null; _hldRenderNav(); };
    });
  }

  // ---- Symbols column
  if (!_hldNav.module) {
    colSyms.innerHTML = `<div class="hld-col-h">Symbols</div>
      <div class="hld-empty">Pick a module →</div>`;
  } else {
    const mod = (hld.modules || {})[_hldNav.module];
    const symbols = mod ? (mod.symbols || []) : [];
    colSyms.innerHTML = `<div class="hld-col-h">Symbols · ${esc(CGUI.shortQn(_hldNav.module))}</div>` +
      (symbols.length
        ? symbols.map(s => {
            const active = _hldNav.symbol === s.qualname ? ' active' : '';
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
      el.onclick = () => { _hldNav.symbol = el.dataset.symbol; _hldRenderNav(); };
    });
  }

  // ---- Crumb
  const parts = [];
  parts.push(`<a class="crumb-link" data-jump="root">All layers</a>`);
  if (_hldNav.layer) parts.push(`<span class="crumb-sep">/</span>
    <a class="crumb-link" data-jump="layer">${esc(_hldLayerTitle(_hldNav.layer))}</a>`);
  if (_hldNav.module) parts.push(`<span class="crumb-sep">/</span>
    <a class="crumb-link qn-mono" data-jump="module">${esc(CGUI.shortQn(_hldNav.module))}</a>`);
  if (_hldNav.symbol) parts.push(`<span class="crumb-sep">/</span>
    <span class="qn-mono">${esc(CGUI.shortQn(_hldNav.symbol))}</span>`);
  crumb.innerHTML = parts.join(' ');
  crumb.querySelectorAll('[data-jump]').forEach(el => {
    el.onclick = () => {
      if (el.dataset.jump === 'root') { _hldNav.layer = _hldNav.module = _hldNav.symbol = null; }
      else if (el.dataset.jump === 'layer') { _hldNav.module = _hldNav.symbol = null; }
      else if (el.dataset.jump === 'module') { _hldNav.symbol = null; }
      _hldRenderNav();
    };
  });

  // ---- Detail panel + focus graph (only when a symbol is selected)
  const focus = document.getElementById('hld-focus');
  if (_hldNav.symbol) {
    const mod = (hld.modules || {})[_hldNav.module];
    const sym = mod && (mod.symbols || []).find(s => s.qualname === _hldNav.symbol);
    if (sym) detail.innerHTML = _symbolDetailHtml(sym, mod);
    detail.querySelectorAll('[data-jumpqn]').forEach(el => {
      el.onclick = () => _jumpToQualname(el.dataset.jumpqn);
    });
    if (sym) _drawFocusGraph(focus, sym);
  } else {
    detail.innerHTML = '';
    if (focus) { focus.style.display = 'none'; focus.innerHTML = ''; }
  }

  lucide.createIcons();
}

function _symbolDetailHtml(sym, mod) {
  const esc = CGUI.esc;
  const formatQn = CGUI.formatQn;
  const kindIcon = CGUI.kindIcon;
  const kindColor = CGUI.kindColor;
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

function _jumpToQualname(qn) {
  // Find the module that owns this qualname (longest prefix match) and select it.
  const mods = (window.state.data.hld.modules || {});
  const candidates = Object.keys(mods).filter(mq => qn === mq || qn.startsWith(mq + '.'));
  if (!candidates.length) return;
  const mqn = candidates.sort((a, b) => b.length - a.length)[0];
  const mod = mods[mqn];
  _hldNav.layer = mod.layer;
  _hldNav.module = mqn;
  _hldNav.symbol = (mod.symbols || []).some(s => s.qualname === qn) ? qn : null;
  _hldRenderNav();
}

function _hldLayerTitle(id) {
  const L = (window.state.data.hld.layers || []).find(x => x.id === id);
  return L ? L.title : id;
}

/* Radial focus graph for the selected symbol. Center = symbol; left arc =
   callers; right arc = callees. Edges are dashed and animated (CSS) to give
   a sense of data flowing inward / outward. Click any node to jump. */
function _drawFocusGraph(svg, sym) {
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
      .on('click', () => _jumpToQualname(qn));
    grp.append('circle').attr('r', 8)
       .attr('class', side === 'in' ? 'focus-dot focus-dot-in' : 'focus-dot focus-dot-out');
    const label = CGUI.shortQn(qn);
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
        .text(CGUI.shortQn(sym.qualname).slice(0, 18));

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
