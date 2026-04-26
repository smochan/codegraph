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
    var hits = getTransform().searchSymbols(hld, query, 20);
    if (!hits.length) {
      box.innerHTML = '<div class="g3d-picker-noresults">No matches.</div>';
      return;
    }
    box.innerHTML = hits.map(pickerResultRowHtml).join('');
    box.querySelectorAll('.g3d-pick-row').forEach(function (btn) {
      btn.addEventListener('click', function () {
        setFocus(host, hld, btn.dataset.qn);
      });
    });
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
    return [
      '<div class="g3d-detail panel p-5">',
      '<div class="text-[11px] uppercase tracking-[0.14em] text-app-3 mb-1">',
      ESC(node.kind), ' · ', ESC(roleLabel),
      (node.file ? (' · ' + ESC(node.file)) : ''),
      (node.layer ? (' · layer ' + ESC(node.layer)) : ''),
      '</div>',
      '<div class="text-base font-semibold qn-mono mb-1"><span class="g3d-detail-name">',
      ESC(node.name || node.id), '</span></div>',
      '<div class="text-xs text-app-3 qn-mono mb-2">', ESC(node.id), '</div>',
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
    try { return window.localStorage && window.localStorage.getItem(LEGEND_KEY) === '1'; }
    catch (e) { return false; }
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
      '<div class="g3d-legend-title">Roles</div>',
      legendDot('#fbbf24', 'Ancestor (caller)'),
      legendDot('#22d3ee', 'Descendant (callee)'),
      legendDot('#a78bfa', 'Current focus'),
      legendDotOutline('External / third-party'),
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
          if (n.external) {
            return '<div class="g3d-tip"><b>' + escapeBasic(n.name) + '</b><br>'
              + escapeBasic(n.qualname) + '<br><i>(external)</i></div>';
          }
          return '<div class="g3d-tip"><b>' + escapeBasic(n.name) + '</b><br>'
            + escapeBasic(n.kind) + ' · ' + escapeBasic(n.role)
            + ' · in ' + (Number(n.fan_in) || 0)
            + ' · out ' + (Number(n.fan_out) || 0) + '</div>';
        })
        .linkColor(function (l) { return l.color; })
        .linkOpacity(0.6)
        .linkDirectionalArrowLength(4)
        .linkDirectionalArrowRelPos(0.92)
        .linkDirectionalParticles(2)
        .linkDirectionalParticleSpeed(0.006)
        .linkWidth(1.2)
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
