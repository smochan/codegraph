/* graph3d.js — 3D Graph view (focus-mode flow tracer) for the codegraph
 * dashboard.
 *
 * Loads as a classic <script>. Reads global state, helpers (esc, showTip,
 * hideTip, toast), and the ForceGraph3D global from the 3d-force-graph CDN.
 * Exposes a single global function: window.renderGraph3d(host).
 *
 * Story (replaces the 0.1.0 "show all 326 nodes" cloud):
 *   1. Default state shows a symbol picker, not a graph.
 *   2. User picks a symbol. We render a small focused subgraph: the root,
 *      its ancestors (callers, amber), and its descendants (callees, cyan),
 *      out to N hops controlled by the depth slider.
 *   3. Clicking any non-root node re-centers the focus on that node.
 *   4. A breadcrumb of the last 3 focuses lets the user jump back.
 *   5. ?demo=1 autoplays a 3-stop tour through hand-picked qualnames.
 *
 * SECURITY: every dynamic value passed into innerHTML goes through ESC()
 * (window.esc fall back to escapeBasic). Static markup is authored inline,
 * matching the convention used by renderOverview / renderHld in app.js.
 */
'use strict';

(function () {
  // ---- Module-level state (one instance per dashboard session) ------------
  var instance = null;
  var demoCtl = null;
  var resizeObs = null;
  var currentHost = null;

  var focus = null;             // { rootQn, depth, direction }
  var focusState = null;        // mutable graph state from makeFocusState
  var history = [];

  var DEFAULT_DEPTH = 2;
  var DEFAULT_DIRECTION = 'both';
  var MAX_HISTORY = 8;

  // Hand-picked tour stops (top fan_in/fan_out symbols of the self-graph).
  var DEMO_STOPS = [
    'codegraph.viz.dashboard.build_dashboard_payload',
    'codegraph.review.risk.score_change',
    'codegraph.parsers.python.PythonExtractor._handle_class',
  ];

  var CDN_URL = 'https://unpkg.com/3d-force-graph@1/dist/3d-force-graph.min.js';

  // ---- Sprite label cache (Change 1) -------------------------------------
  //
  // Build a THREE.Sprite text label per node so labels stay visible at all
  // camera distances. Labels are cached per node id to avoid GC churn during
  // re-renders. Distance fade is handled implicitly via sprite scale: a
  // smaller canvas projects a smaller label far from the camera, keeping
  // foreground nodes readable without an explicit per-tick LOD pass.
  var SPRITE_CACHE = new Map();

  function makeLabelSprite(text) {
    var SpriteText = (typeof window !== 'undefined') ? window.SpriteText : null;
    if (typeof SpriteText !== 'function') return null;
    var sprite = new SpriteText(String(text || ''));
    sprite.color = '#f1f5ff';
    sprite.backgroundColor = 'rgba(8,12,20,0.55)';
    sprite.padding = 2;
    sprite.borderRadius = 3;
    sprite.fontFace = 'Inter, ui-sans-serif, system-ui, sans-serif';
    sprite.fontWeight = 'bold';
    sprite.textHeight = 6;
    return sprite;
  }

  // ---- Edge arg label (Change 2 / DF0) ----------------------------------
  //
  // Render a small monospace sprite at the midpoint of CALLS edges that
  // carry a non-empty argLabel (produced by the transform from the
  // payload's parallel callee_args array).
  function makeEdgeLabelSprite(text) {
    if (typeof window.THREE === 'undefined') return null;
    var THREE = window.THREE;
    var fontPx = 28;
    var pad = 4;
    var canvas = document.createElement('canvas');
    var ctx = canvas.getContext('2d');
    ctx.font = fontPx + 'px ui-monospace, SFMono-Regular, Menlo, monospace';
    var w = Math.ceil(ctx.measureText(String(text || '')).width) + pad * 2;
    var h = fontPx + pad * 2;
    canvas.width = w;
    canvas.height = h;
    ctx.font = fontPx + 'px ui-monospace, SFMono-Regular, Menlo, monospace';
    ctx.textBaseline = 'middle';
    ctx.textAlign = 'center';
    ctx.fillStyle = 'rgba(8,12,20,0.6)';
    ctx.fillRect(0, 0, w, h);
    ctx.fillStyle = '#cbd5f5';
    ctx.fillText(String(text || ''), w / 2, h / 2 + 1);
    var texture = new THREE.CanvasTexture(canvas);
    texture.minFilter = THREE.LinearFilter;
    var material = new THREE.SpriteMaterial({
      map: texture, transparent: true, depthWrite: false,
    });
    var sprite = new THREE.Sprite(material);
    var scale = 0.14;
    sprite.scale.set(w * scale, h * scale, 1);
    return sprite;
  }

  var EDGE_SPRITE_CACHE = new Map();
  function getOrMakeEdgeLabelSprite(link) {
    if (!link) return null;
    var text = link.argLabel || '';
    if (!text) return null;
    var key = (link.source && link.source.id || link.source) + '->'
      + (link.target && link.target.id || link.target) + '|' + text;
    var cached = EDGE_SPRITE_CACHE.get(key);
    if (cached) return cached;
    var sprite = makeEdgeLabelSprite(text);
    if (sprite) EDGE_SPRITE_CACHE.set(key, sprite);
    return sprite;
  }
  function clearEdgeSpriteCache() { EDGE_SPRITE_CACHE.clear(); }

  function getOrMakeLabelSprite(node) {
    if (!node) return null;
    var cached = SPRITE_CACHE.get(node.id);
    if (cached) return cached.sprite;
    var sprite = makeLabelSprite(node.name || node.id);
    if (!sprite) return null;
    SPRITE_CACHE.set(node.id, { sprite: sprite });
    return sprite;
  }
  function clearSpriteCache() { SPRITE_CACHE.clear(); }

  function getTransform() {
    var T = window.CG_Graph3DTransform;
    if (!T) throw new Error('graph3d_transform.js not loaded');
    return T;
  }
  function isLight() {
    return document.documentElement.classList.contains('theme-light');
  }
  function bgColor() { return isLight() ? '#f4f6fb' : '#05070d'; }
  function hasWebGL() {
    try {
      var c = document.createElement('canvas');
      return !!(c.getContext('webgl') || c.getContext('experimental-webgl'));
    } catch (e) { return false; }
  }
  function loadLibrary() {
    if (typeof window.ForceGraph3D !== 'undefined') return Promise.resolve();
    return new Promise(function (resolve, reject) {
      var existing = document.querySelector('script[data-cg-3dfg]');
      if (existing) {
        existing.addEventListener('load', resolve);
        existing.addEventListener('error', reject);
        return;
      }
      var s = document.createElement('script');
      s.src = CDN_URL;
      s.async = true;
      s.dataset.cg3dfg = '1';
      s.onload = resolve;
      s.onerror = function () { reject(new Error('CDN load failed')); };
      document.head.appendChild(s);
    });
  }
  function escapeBasic(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return ({ '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;' })[c];
    });
  }
  var ESC = (typeof window !== 'undefined' && window.esc) || escapeBasic;

  function destroyScene() {
    if (demoCtl) { try { demoCtl.destroy(); } catch (e) {} demoCtl = null; }
    if (instance) {
      try { instance._destructor && instance._destructor(); } catch (e) {}
      instance = null;
    }
    if (resizeObs) { try { resizeObs.disconnect(); } catch (e) {} resizeObs = null; }
    clearSpriteCache();
    clearEdgeSpriteCache();
  }

  function fallbackHtml(msg) {
    return [
      '<div class="p-8 max-w-4xl mx-auto">',
      '<div class="help-card mb-6">',
      '<i data-lucide="alert-triangle" class="icon w-4 h-4"></i>',
      '<div><b>3D Graph unavailable.</b> ', ESC(msg), '</div>',
      '</div>',
      '<div class="g3d-fallback panel p-6">',
      '<p class="mb-4 text-app-2">Try the 2D HLD view instead.</p>',
      '<button class="g3d-filter-btn active" id="g3d-fallback-hld">Open HLD</button>',
      '</div></div>',
    ].join('');
  }
  function wireFallback(host) {
    if (window.lucide) window.lucide.createIcons();
    var btn = host.querySelector('#g3d-fallback-hld');
    if (btn && typeof window.activate === 'function') {
      btn.addEventListener('click', function () { window.activate('hld'); });
    }
  }

  // ---- Picker shell ------------------------------------------------------
  function pickerShellHtml() {
    return [
      '<div class="p-6 max-w-7xl mx-auto" id="g3d-shell">',
      '<div class="help-card mb-4">',
      '<i data-lucide="atom" class="icon w-4 h-4"></i>',
      '<div><b>3D flow tracer.</b> Pick a symbol to trace its data flow — ',
      'callers flow in, callees flow out, click any node to recenter.</div>',
      '</div>',
      '<div id="g3d-bar"></div>',
      '<div id="g3d-breadcrumb"></div>',
      '<div id="g3d-stage"></div>',
      '</div>',
    ].join('');
  }
  function searchInputHtml(value) {
    return [
      '<div class="g3d-search">',
      '<i data-lucide="search" class="icon w-4 h-4 g3d-search-icon"></i>',
      '<input type="text" id="g3d-search-input" placeholder="Search symbols by name or qualname…" ',
      'autocomplete="off" spellcheck="false" value="', ESC(value || ''), '" />',
      '</div>',
    ].join('');
  }
  function pickerEmptyStageHtml() {
    return [
      '<div class="g3d-picker-stage">',
      '<div class="g3d-picker-results" id="g3d-picker-results"></div>',
      '<div class="g3d-picker-empty">',
      '<i data-lucide="compass" class="icon w-8 h-8"></i>',
      '<h3>Pick a symbol to trace its data flow.</h3>',
      '<p>Search above. The graph renders only the chosen symbol’s neighborhood — ',
      'no more 326-node cloud.</p>',
      '</div>',
      '</div>',
    ].join('');
  }
  function kindBadge(kind) {
    var k = String(kind || '').toUpperCase();
    return '<span class="g3d-kind-badge g3d-kind-' + ESC(k.toLowerCase()) + '">'
      + ESC(k || '?') + '</span>';
  }
  function pickerResultRowHtml(r) {
    return [
      '<button class="g3d-pick-row" data-qn="', ESC(r.qualname), '">',
      kindBadge(r.kind),
      '<span class="g3d-pick-name">', ESC(r.name || r.qualname), '</span>',
      '<span class="g3d-pick-qn">', ESC(r.qualname), '</span>',
      '<span class="g3d-pick-meta">in ', Number(r.fan_in) || 0,
      ' · out ', Number(r.fan_out) || 0, '</span>',
      '</button>',
    ].join('');
  }
  function renderPickerResults(host, hld, query) {
    var box = host.querySelector('#g3d-picker-results');
    if (!box) return;
    var T = getTransform();
    var roleGroups = T.filterGroupedByRole(T.groupSymbolsByRole(hld), query);
    var nonEmpty = roleGroups.filter(function (rg) { return rg.modules.length; });
    if (!nonEmpty.length) {
      box.innerHTML = '<div class="g3d-picker-noresults">No matches.</div>';
      return;
    }
    box.innerHTML = nonEmpty.map(pickerRoleBucketHtml).join('');
    box.querySelectorAll('.g3d-pick-row').forEach(function (btn) {
      btn.addEventListener('click', function () {
        setFocus(host, hld, btn.dataset.qn);
      });
    });
  }

  function pickerRoleBucketHtml(rg) {
    var modules = rg.modules.map(pickerGroupHtml).join('');
    return [
      '<div class="g3d-role-bucket">',
      '<div class="g3d-role-bucket-hdr">',
      '<span class="g3d-role-chip" style="background:', ESC(rg.color), ';"></span>',
      '<span class="g3d-role-bucket-name">', ESC(rg.role), '</span>',
      '<span class="g3d-role-bucket-count">', rg.modules.length, ' module',
      (rg.modules.length === 1 ? '' : 's'), '</span>',
      '</div>',
      '<div class="g3d-role-bucket-body">',
      modules,
      '</div>',
      '</div>',
    ].join('');
  }

  function pickerGroupHtml(g) {
    var classBlocks = g.classes.map(pickerClassHtml).join('');
    var fnBlocks = g.functions.map(function (f) {
      return pickerLeafHtml(f, false);
    }).join('');
    return [
      '<div class="g3d-grp">',
      '<div class="g3d-grp-hdr">',
      '<span class="g3d-grp-tag">MOD</span>',
      '<span class="g3d-grp-name qn-mono">', ESC(g.qualname), '</span>',
      (g.file ? '<span class="g3d-grp-file">' + ESC(g.file) + '</span>' : ''),
      '</div>',
      '<div class="g3d-grp-body">',
      classBlocks,
      fnBlocks,
      '</div>',
      '</div>',
    ].join('');
  }
  function pickerClassHtml(c) {
    var methods = c.methods.map(function (m) { return pickerLeafHtml(m, true); }).join('');
    return [
      '<div class="g3d-grp-class">',
      '<div class="g3d-grp-class-hdr">',
      '<span class="g3d-kind-badge g3d-kind-class">C</span>',
      '<span class="g3d-grp-class-name">', ESC(c.name), '</span>',
      '</div>',
      methods,
      '</div>',
    ].join('');
  }
  function pickerLeafHtml(s, indent) {
    var k = String(s.kind || '').toUpperCase();
    var badge = k === 'METHOD' ? 'M' : (k === 'FUNCTION' ? 'FN' : (k.slice(0, 3) || '?'));
    return [
      '<button class="g3d-pick-row', (indent ? ' g3d-pick-indent' : ''),
      '" data-qn="', ESC(s.qualname), '">',
      '<span class="g3d-kind-badge g3d-kind-', ESC(k.toLowerCase()), '">',
      ESC(badge), '</span>',
      '<span class="g3d-pick-name">', ESC(s.name || s.qualname), '</span>',
      '<span class="g3d-pick-meta">in ', Number(s.fan_in) || 0,
      ' · out ', Number(s.fan_out) || 0, '</span>',
      '</button>',
    ].join('');
  }

  // ---- Controls bar ------------------------------------------------------
  function controlsBarHtml(focusState, nodeCount) {
    var d = focusState ? focusState.depth : DEFAULT_DEPTH;
    var dir = focusState ? focusState.direction : DEFAULT_DIRECTION;
    var dirBtn = function (val, label) {
      var on = (dir === val) ? ' active' : '';
      return '<button class="g3d-filter-btn' + on + '" data-dir="' + ESC(val)
        + '">' + ESC(label) + '</button>';
    };
    return [
      '<div class="g3d-controls">',
      '<div class="g3d-controls-group g3d-controls-search">',
      searchInputHtml(focusState ? focusState.rootQn : ''),
      '</div>',
      '<div class="g3d-controls-sep"></div>',
      '<div class="g3d-controls-group">',
      '<span class="g3d-controls-lbl">Depth</span>',
      '<input type="range" id="g3d-depth" min="1" max="4" step="1" value="', d, '" />',
      '<span class="g3d-depth-val" id="g3d-depth-val">', d, '</span>',
      '</div>',
      '<div class="g3d-controls-sep"></div>',
      '<div class="g3d-controls-group">',
      dirBtn('ancestors',   'Ancestors'),
      dirBtn('both',        'Both'),
      dirBtn('descendants', 'Descendants'),
      '</div>',
      '<div class="g3d-controls-sep"></div>',
      '<div class="g3d-controls-group">',
      '<button class="g3d-filter-btn" id="g3d-demo-btn" title="Autoplay tour">Demo</button>',
      '<button class="g3d-filter-btn" id="g3d-reset-btn" title="Reset to picker">Reset to picker</button>',
      '<span class="g3d-controls-lbl ml-auto g3d-node-count">',
      Number(nodeCount) || 0, ' nodes</span>',
      '</div>',
      '</div>',
      '<div id="g3d-search-popover" class="g3d-search-popover" hidden></div>',
    ].join('');
  }

  function breadcrumbHtml() {
    if (!history.length) return '';
    var recent = history.slice(-3);
    var crumbs = recent.map(function (qn) {
      var isCurrent = (focus && qn === focus.rootQn);
      return '<button class="g3d-crumb' + (isCurrent ? ' is-current' : '')
        + '" data-qn="' + ESC(qn) + '">' + ESC(qn) + '</button>';
    });
    return [
      '<div class="g3d-breadcrumb">',
      '<span class="g3d-breadcrumb-lbl">Trail</span>',
      crumbs.join('<span class="g3d-breadcrumb-sep">›</span>'),
      '</div>',
    ].join('');
  }

  function pushHistory(qn) {
    if (!qn) return;
    if (history.length && history[history.length - 1] === qn) return;
    history.push(qn);
    while (history.length > MAX_HISTORY) history.shift();
  }
  function setFocus(host, hld, qn) {
    if (!qn) return;
    focus = {
      rootQn: qn,
      depth: focus ? focus.depth : DEFAULT_DEPTH,
      direction: focus ? focus.direction : DEFAULT_DIRECTION,
    };
    focusState = getTransform().makeFocusState(hld, qn, focus.depth, focus.direction);
    pushHistory(qn);
    renderFocusedView(host, hld);
  }
  function clearFocus(host, hld) {
    focus = null;
    focusState = null;
    history = [];
    renderPickerView(host, hld);
  }
  function toggleExpand(host, hld, qn) {
    if (!focusState || !qn) return;
    if (qn === focus.rootQn) return;
    var T = getTransform();
    if (T.isExpanded(focusState, qn)) {
      T.collapseNode(focusState, qn);
    } else {
      T.expandNode(focusState, hld, qn);
    }
    refreshGraphData(host);
  }

  // Per-node detail panel.
  //
  // Intentionally does NOT show fan_in / fan_out (Item 5): those are
  // graph-theory metrics that fit the Hotspots view, not the data-flow
  // story this 3D view tells. Detail shows: name, qualname, kind, file,
  // role, layer (if present), plus action buttons (Expand / Set as root)
  // for non-external internal nodes.
  function detailHtml(node) {
    var roleLabel = ({
      root: 'root', ancestor: 'caller', descendant: 'callee', external: 'external',
    })[node.role] || node.role || '';
    var expanded = focusState && getTransform().isExpanded(focusState, node.id);
    var actions = '';
    if (!node.external && node.role !== 'root') {
      actions = [
        '<div class="g3d-detail-actions mt-3">',
        '<button class="g3d-filter-btn" data-action="toggle-expand" data-qn="', ESC(node.id), '">',
        expanded ? 'Collapse neighbors' : 'Expand neighbors',
        '</button>',
        '<button class="g3d-filter-btn" data-action="set-root" data-qn="', ESC(node.id), '">',
        'Set as root',
        '</button>',
        '</div>',
      ].join('');
    }
    var T = getTransform();
    var signature = T.formatSignature ? T.formatSignature(node) : '';
    var sigBlock = '';
    if (signature) {
      sigBlock = [
        '<div class="g3d-detail-sig-lbl">Signature</div>',
        '<div class="g3d-detail-sig">', ESC(signature), '</div>',
      ].join('');
    }
    var roleChip = '';
    if (node.symbolRole) {
      var color = (T.ROLE_PICKER_COLORS && T.ROLE_PICKER_COLORS[node.symbolRole]) || '#8b9ab8';
      roleChip = [
        '<span class="g3d-detail-rolechip" style="background:', ESC(color), ';"></span>',
        '<span class="g3d-detail-role-name">', ESC(node.symbolRole), '</span>',
      ].join('');
    }
    return [
      '<div class="g3d-detail panel p-5">',
      '<div class="text-[11px] uppercase tracking-[0.14em] text-app-3 mb-1">',
      ESC(node.kind), ' · ', ESC(roleLabel),
      (node.file ? (' · ' + ESC(node.file)) : ''),
      (node.layer ? (' · layer ' + ESC(node.layer)) : ''),
      '</div>',
      '<div class="text-base font-semibold qn-mono mb-1"><span class="g3d-detail-name">',
      ESC(node.name || node.id), '</span>',
      (roleChip ? ' <span class="g3d-detail-role">' + roleChip + '</span>' : ''),
      '</div>',
      '<div class="text-xs text-app-3 qn-mono mb-2">', ESC(node.id), '</div>',
      sigBlock,
      (node.external
        ? '<div class="g3d-detail-hint mt-1">External symbol — terminal leaf.</div>'
        : ''),
      actions,
      '</div>',
    ].join('');
  }

  function renderDetail(el, node) {
    if (!el || !node) return;
    el.innerHTML = detailHtml(node);
    el.querySelectorAll('[data-action]').forEach(function (btn) {
      btn.addEventListener('click', function () {
        var action = btn.dataset.action;
        var qn = btn.dataset.qn;
        if (action === 'toggle-expand') {
          toggleExpand(currentHost, currentHldRef(), qn);
          // Re-render detail to flip Expand/Collapse label.
          var fresh = focusState && focusState.nodes && focusState.nodes.get(qn);
          if (fresh) renderDetail(el, fresh);
        } else if (action === 'set-root') {
          setFocus(currentHost, currentHldRef(), qn);
        }
      });
    });
  }

  function currentHldRef() {
    return (window.state && window.state.data && window.state.data.hld) || { modules: {} };
  }

  function renderShell(host) {
    host.innerHTML = pickerShellHtml();
    if (window.lucide) window.lucide.createIcons();
  }

  function renderPickerView(host, hld) {
    destroyScene();
    renderShell(host);
    var bar = host.querySelector('#g3d-bar');
    bar.innerHTML = [
      '<div class="g3d-controls">',
      '<div class="g3d-controls-group g3d-controls-search g3d-controls-search-large">',
      searchInputHtml(''),
      '</div>',
      '<div class="g3d-controls-group">',
      '<button class="g3d-filter-btn" id="g3d-demo-btn">Demo tour</button>',
      '</div>',
      '</div>',
    ].join('');
    host.querySelector('#g3d-stage').innerHTML = pickerEmptyStageHtml();
    if (window.lucide) window.lucide.createIcons();
    wirePickerInputs(host, hld);
    renderPickerResults(host, hld, '');
  }

  function wirePickerInputs(host, hld) {
    var input = host.querySelector('#g3d-search-input');
    if (input) {
      input.addEventListener('input', function () {
        renderPickerResults(host, hld, input.value);
      });
      input.addEventListener('keydown', function (e) {
        if (e.key === 'Enter') {
          var first = host.querySelector('.g3d-pick-row');
          if (first) first.click();
        }
      });
      setTimeout(function () { try { input.focus(); } catch (e) {} }, 30);
    }
    var demoBtn = host.querySelector('#g3d-demo-btn');
    if (demoBtn) demoBtn.addEventListener('click', function () { startDemoTour(host, hld); });
  }

  // ---- Color & kind legend (Item 3) -------------------------------------
  var LEGEND_KEY = 'cg-3d-legend-collapsed';
  function legendCollapsed() {
    // Change 5: legend is expanded by default. Only collapsed when the
    // user has explicitly stored '1'. Absence of the key => expanded.
    try {
      if (!window.localStorage) return false;
      return window.localStorage.getItem(LEGEND_KEY) === '1';
    } catch (e) { return false; }
  }
  function setLegendCollapsed(v) {
    try { window.localStorage && window.localStorage.setItem(LEGEND_KEY, v ? '1' : '0'); }
    catch (e) { /* ignore quota / SecurityError */ }
  }
  function legendHtml() {
    var collapsed = legendCollapsed();
    return [
      '<div class="g3d-legend', (collapsed ? ' is-collapsed' : ''), '" id="g3d-legend">',
      '<button class="g3d-legend-toggle" id="g3d-legend-toggle" ',
      'title="', (collapsed ? 'Show legend' : 'Hide legend'), '" ',
      'aria-label="Toggle legend">',
      (collapsed ? '?' : '×'),
      '</button>',
      '<div class="g3d-legend-body">',
      '<div class="g3d-legend-section">',
      '<div class="g3d-legend-title">Flow</div>',
      legendDot('#fbbf24', 'Ancestor (caller)'),
      legendDot('#22d3ee', 'Descendant (callee)'),
      legendDot('#a78bfa', 'Current focus'),
      legendDotOutline('External / third-party'),
      '</div>',
      '<div class="g3d-legend-section">',
      '<div class="g3d-legend-title">Role</div>',
      legendDot('#fbbf24', 'HANDLER'),
      legendDot('#3b82f6', 'SERVICE'),
      legendDot('#34d399', 'COMPONENT'),
      legendDot('#c084fc', 'REPO'),
      legendDot('#8b9ab8', 'no role'),
      '</div>',
      '<div class="g3d-legend-section">',
      '<div class="g3d-legend-title">Kinds</div>',
      '<div class="g3d-legend-kinds">',
      '<span class="g3d-kind-badge g3d-kind-function">FN</span>',
      '<span class="g3d-kind-badge g3d-kind-method">M</span>',
      '<span class="g3d-kind-badge g3d-kind-class">C</span>',
      '<span class="g3d-kind-badge g3d-kind-module">MOD</span>',
      '</div>',
      '</div>',
      '</div>',
      '</div>',
    ].join('');
  }
  function legendDot(color, label) {
    return [
      '<div class="g3d-legend-row">',
      '<span class="g3d-legend-dot" style="background:', ESC(color), ';"></span>',
      '<span class="g3d-legend-lbl">', ESC(label), '</span>',
      '</div>',
    ].join('');
  }
  function legendDotOutline(label) {
    return [
      '<div class="g3d-legend-row">',
      '<span class="g3d-legend-dot g3d-legend-dot-outline"></span>',
      '<span class="g3d-legend-lbl">', ESC(label), '</span>',
      '</div>',
    ].join('');
  }
  function wireLegend(host) {
    var btn = host.querySelector('#g3d-legend-toggle');
    var legend = host.querySelector('#g3d-legend');
    if (!btn || !legend) return;
    btn.addEventListener('click', function () {
      var nowCollapsed = !legend.classList.contains('is-collapsed');
      legend.classList.toggle('is-collapsed', nowCollapsed);
      btn.textContent = nowCollapsed ? '?' : '×';
      btn.title = nowCollapsed ? 'Show legend' : 'Hide legend';
      setLegendCollapsed(nowCollapsed);
    });
  }

  function refreshGraphData(host) {
    if (!instance || !focusState) return;
    var snap = getTransform().snapshotState(focusState);
    instance.graphData(snap);
    var bar = host && host.querySelector && host.querySelector('#g3d-bar');
    if (bar) {
      var countEl = bar.querySelector('.g3d-node-count');
      if (countEl) countEl.textContent = snap.nodes.length + ' nodes';
    }
  }

  function renderFocusedView(host, hld) {
    destroyScene();
    renderShell(host);

    var T = getTransform();
    if (!focusState) {
      focusState = T.makeFocusState(hld, focus.rootQn, focus.depth, focus.direction);
    }
    var data = T.snapshotState(focusState);

    host.querySelector('#g3d-bar').innerHTML = controlsBarHtml(focus, data.nodes.length);
    host.querySelector('#g3d-breadcrumb').innerHTML = breadcrumbHtml();

    var stage = host.querySelector('#g3d-stage');
    stage.innerHTML = [
      '<div class="g3d-canvas-wrap" id="g3d-canvas">',
      legendHtml(),
      '</div>',
      '<div id="g3d-detail" class="mt-4"></div>',
    ].join('');
    wireLegend(host);

    if (window.lucide) window.lucide.createIcons();
    wireFocusedInputs(host, hld);

    if (data.nodes.length === 0) {
      var canvas = host.querySelector('#g3d-canvas');
      canvas.textContent = '';
      var msg = document.createElement('div');
      msg.className = 'g3d-empty';
      msg.textContent = 'No nodes — try a different direction or a larger depth.';
      canvas.appendChild(msg);
      return;
    }

    loadLibrary().then(function () {
      bootScene(host, hld, data);
    }).catch(function () {
      host.innerHTML = fallbackHtml('3D Graph library failed to load.');
      wireFallback(host);
      if (window.toast) window.toast('3D graph library unavailable.', 'error');
    });
  }

  function wireFocusedInputs(host, hld) {
    var input = host.querySelector('#g3d-search-input');
    if (input) {
      input.addEventListener('focus', function () { showSearchPopover(host, hld, input.value); });
      input.addEventListener('input', function () { showSearchPopover(host, hld, input.value); });
      input.addEventListener('blur', function () {
        setTimeout(function () { hideSearchPopover(host); }, 150);
      });
      input.addEventListener('keydown', function (e) {
        if (e.key === 'Enter') {
          var first = host.querySelector('.g3d-search-popover .g3d-pick-row');
          if (first) first.click();
        } else if (e.key === 'Escape') {
          hideSearchPopover(host);
          input.blur();
        }
      });
    }
    var depthInput = host.querySelector('#g3d-depth');
    if (depthInput) {
      depthInput.addEventListener('input', function () {
        var v = Number(depthInput.value) || DEFAULT_DEPTH;
        host.querySelector('#g3d-depth-val').textContent = String(v);
        focus.depth = v;
        // Depth controls initial fold-out only — rebuild state from scratch.
        focusState = getTransform().makeFocusState(hld, focus.rootQn, focus.depth, focus.direction);
        renderFocusedView(host, hld);
      });
    }
    host.querySelectorAll('.g3d-filter-btn[data-dir]').forEach(function (btn) {
      btn.addEventListener('click', function () {
        focus.direction = btn.dataset.dir;
        focusState = getTransform().makeFocusState(hld, focus.rootQn, focus.depth, focus.direction);
        renderFocusedView(host, hld);
      });
    });
    var resetBtn = host.querySelector('#g3d-reset-btn');
    if (resetBtn) resetBtn.addEventListener('click', function () { clearFocus(host, hld); });
    var demoBtn = host.querySelector('#g3d-demo-btn');
    if (demoBtn) demoBtn.addEventListener('click', function () { startDemoTour(host, hld); });
    host.querySelectorAll('.g3d-crumb').forEach(function (btn) {
      btn.addEventListener('click', function () {
        var qn = btn.dataset.qn;
        if (qn && focus && qn !== focus.rootQn) {
          focus.rootQn = qn;
          pushHistory(qn);
          renderFocusedView(host, hld);
        }
      });
    });
  }

  function showSearchPopover(host, hld, query) {
    var pop = host.querySelector('#g3d-search-popover');
    if (!pop) return;
    var hits = getTransform().searchSymbols(hld, query, 20);
    if (!hits.length) {
      pop.innerHTML = '<div class="g3d-picker-noresults">No matches.</div>';
    } else {
      pop.innerHTML = hits.map(pickerResultRowHtml).join('');
      pop.querySelectorAll('.g3d-pick-row').forEach(function (btn) {
        btn.addEventListener('mousedown', function (e) {
          e.preventDefault();
          setFocus(host, hld, btn.dataset.qn);
        });
      });
    }
    pop.hidden = false;
  }
  function hideSearchPopover(host) {
    var pop = host.querySelector('#g3d-search-popover');
    if (pop) pop.hidden = true;
  }

  function injectLegendOverlay(host) {
    // ForceGraph3D() overwrites the container's contents on mount, so we
    // attach the legend AFTER mount as a positioned sibling overlay inside
    // the same wrap. Idempotent — replaces a stale legend if present.
    var stage = host.querySelector('#g3d-stage');
    if (!stage) return;
    var prior = host.querySelector('#g3d-legend');
    if (prior && prior.parentNode) prior.parentNode.removeChild(prior);
    var temp = document.createElement('div');
    temp.innerHTML = legendHtml();  // trusted, all-internal
    var legend = temp.firstChild;
    if (!legend) return;
    var canvasWrap = host.querySelector('#g3d-canvas');
    var parent = canvasWrap ? canvasWrap.parentElement : stage;
    parent.style.position = parent.style.position || 'relative';
    parent.appendChild(legend);
    wireLegend(host);
  }

  function bootScene(host, hld, data) {
    var container = host.querySelector('#g3d-canvas');
    if (!container || typeof window.ForceGraph3D === 'undefined') return;
    var detailEl = host.querySelector('#g3d-detail');

    try {
      instance = window.ForceGraph3D()(container)
        .backgroundColor(bgColor())
        .nodeRelSize(4)
        .nodeColor(function (n) { return n.color; })
        .nodeVal(function (n) { return n.val; })
        .nodeLabel(function (n) {
          // Library-native HTML hover label (no THREE required).
          // Always renders: name (large), kind+role (small), signature if present.
          if (n.external) {
            return '<div class="g3d-tip"><b>' + escapeBasic(n.name) + '</b>'
              + '<div class="g3d-tip-meta">' + escapeBasic(n.qualname)
              + ' · <i>external</i></div></div>';
          }
          var T = (typeof window !== 'undefined' && window.CG_Graph3DTransform) || null;
          var sig = (T && typeof T.formatSignature === 'function')
            ? T.formatSignature(n) : '';
          var sigHtml = sig
            ? '<div class="g3d-tip-sig">' + escapeBasic(sig) + '</div>' : '';
          var roleHtml = n.symbolRole
            ? ' · <span class="g3d-tip-role">' + escapeBasic(n.symbolRole) + '</span>'
            : '';
          return '<div class="g3d-tip"><b>' + escapeBasic(n.name) + '</b>'
            + '<div class="g3d-tip-meta">' + escapeBasic(n.kind) + roleHtml + '</div>'
            + sigHtml + '</div>';
        })
        .linkColor(function (l) { return l.color; })
        .linkOpacity(0.6)
        .linkDirectionalArrowLength(4)
        .linkDirectionalArrowRelPos(0.92)
        .linkDirectionalParticles(2)
        .linkDirectionalParticleSpeed(0.006)
        .linkWidth(1.2)
        .linkLabel(function (l) {
          if (!l.argLabel) return '';
          return '<div class="g3d-tip g3d-tip-edge"><b>args</b>: '
            + escapeBasic(l.argLabel) + '</div>';
        })
        .nodeThreeObjectExtend(true)
        .nodeThreeObject(function (n) { return getOrMakeLabelSprite(n); })
        .onNodeHover(function (node) {
          container.style.cursor = node ? 'pointer' : 'grab';
        })
        .onNodeClick(function (node, evt) {
          if (!node) return;
          renderDetail(detailEl, node);
          // External (stdlib / third-party) leaves are terminal — show
          // detail but never recenter / expand on them.
          if (node.external) return;
          if (node.role === 'root') {
            // Camera nudge only.
            var dist = 100;
            var len = Math.hypot(node.x || 1, node.y || 1, node.z || 1) || 1;
            instance.cameraPosition(
              { x: node.x * (1 + dist / len),
                y: node.y * (1 + dist / len),
                z: node.z * (1 + dist / len) },
              node, 800
            );
            return;
          }
          // Shift-click pivots: drop current state, set this node as root.
          if (evt && (evt.shiftKey || evt.metaKey)) {
            setFocus(host, hld, node.id);
            return;
          }
          // Default: expand 1-hop neighbors inline (or collapse if already
          // expanded). Root and externals are excluded above.
          toggleExpand(host, hld, node.id);
        })
        .graphData(data);

      if (typeof ResizeObserver !== 'undefined') {
        resizeObs = new ResizeObserver(function () {
          if (instance && container.clientWidth) {
            instance.width(container.clientWidth).height(container.clientHeight);
          }
        });
        resizeObs.observe(container);
      }
      injectLegendOverlay(host);
    } catch (e) {
      host.innerHTML = fallbackHtml('WebGL initialization failed: ' + (e && e.message || e));
      wireFallback(host);
    }
  }

  function pickAvailableDemoStops(hld) {
    var T = getTransform();
    var index = {};
    var modules = (hld && hld.modules) || {};
    Object.keys(modules).forEach(function (mqn) {
      ((modules[mqn] || {}).symbols || []).forEach(function (s) {
        if (s && s.qualname) index[s.qualname] = true;
      });
    });
    var stops = DEMO_STOPS.filter(function (qn) { return index[qn]; });
    if (stops.length >= 2) return stops;
    return T.searchSymbols(hld, '', 3).map(function (h) { return h.qualname; });
  }

  function startDemoTour(host, hld) {
    var stops = pickAvailableDemoStops(hld);
    if (!stops.length) return;
    if (demoCtl) { try { demoCtl.destroy(); } catch (e) {} demoCtl = null; }

    var i = 0;
    var stopped = false;
    var ctl = {
      _timer: null,
      destroy: function () {
        stopped = true;
        if (this._timer) clearTimeout(this._timer);
      },
    };
    demoCtl = ctl;
    function step() {
      if (stopped) return;
      var qn = stops[i % stops.length];
      setFocus(host, hld, qn);
      i++;
      ctl._timer = setTimeout(step, 5500);
    }
    step();
  }

  function renderGraph3d(host) {
    currentHost = host;
    destroyScene();

    var hld = (window.state && window.state.data && window.state.data.hld) || { modules: {} };

    if (!hasWebGL()) {
      host.innerHTML = fallbackHtml('WebGL is not supported in this browser.');
      wireFallback(host);
      return;
    }

    if (focus && focus.rootQn) {
      renderFocusedView(host, hld);
    } else {
      renderPickerView(host, hld);
    }

    if (new URLSearchParams(location.search).get('demo') === '1' && !focus) {
      setTimeout(function () { startDemoTour(host, hld); }, 200);
    }
  }

  window.renderGraph3d = renderGraph3d;
})();
