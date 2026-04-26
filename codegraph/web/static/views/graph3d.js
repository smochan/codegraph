/* graph3d.js — 3D Graph view renderer for the codegraph dashboard.
 *
 * Loads as a classic <script>. Reads global state, helpers (esc, showTip,
 * hideTip, toast), and the ForceGraph3D global from the 3d-force-graph CDN.
 * Exposes a single global function: window.renderGraph3d(host).
 *
 * MANUAL SMOKE TEST (Playwright is not yet installed in this repo):
 *   1. python -m codegraph build && python -m codegraph serve
 *   2. open http://127.0.0.1:8765/#graph3d
 *   3. confirm sidebar entry "3D Graph" is selected
 *   4. confirm a WebGL <canvas> renders inside #view-host with rotating nodes
 *   5. hover a node — tooltip should show qualname / kind / fan-in / fan-out
 *   6. click a node — camera focuses, details panel renders below the canvas
 *   7. toggle a kind filter button — the graph rebuilds without a context recreate
 *   8. open http://127.0.0.1:8765/?demo=1#graph3d — auto-rotate + hotspot zoom loop
 *   9. flip theme — graph reinstantiates with the matching background
 *  10. (negative) block the unpkg CDN — fallback message + toast appears
 *
 * All HTML insertion uses esc()/escapeBasic() on every string that originates
 * outside this file (node names, file paths, qualnames). Static markup is
 * authored inline, matching the convention used by renderOverview / renderHld
 * in app.js. No user-supplied attribute interpolation.
 */
'use strict';

(function () {
  // ---- Module-level state (one instance per dashboard session) ----
  var instance = null;          // ForceGraph3D instance
  var demoCtl = null;           // DemoController instance
  var resizeObs = null;
  var lastFilters = null;       // remembered between rebuilds in same session

  var ALL_KINDS = ['FUNCTION', 'METHOD', 'CLASS', 'MODULE'];
  var ALL_EDGES = ['CALLS', 'IMPORTS', 'INHERITS'];

  var LABEL_THRESHOLD = 2000;
  var DETAIL_THRESHOLD = 5000;

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

  // ---- Filter state ----
  function defaultFilters() {
    return {
      kinds: new Set(ALL_KINDS),
      edgeKinds: new Set(ALL_EDGES),
    };
  }

  // ---- Tear-down ----
  function teardown() {
    if (demoCtl) { try { demoCtl.destroy(); } catch (e) { /* ignore */ } demoCtl = null; }
    if (instance) {
      try { instance._destructor && instance._destructor(); } catch (e) { /* ignore */ }
      instance = null;
    }
    if (resizeObs) { try { resizeObs.disconnect(); } catch (e) {} resizeObs = null; }
  }

  function escapeBasic(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return ({ '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;' })[c];
    });
  }
  var ESC = (typeof window !== 'undefined' && window.esc) || escapeBasic;

  // ---- Fallback UI ----
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

  // ---- Details panel ----
  function detailHtml(node) {
    return [
      '<div class="g3d-detail panel p-5">',
      '<div class="text-[11px] uppercase tracking-[0.14em] text-app-3 mb-1">',
      ESC(node.kind), ' · ', ESC(node.file), '</div>',
      '<div class="text-base font-semibold qn-mono mb-3">', ESC(node.id), '</div>',
      '<div class="flex gap-4 text-xs text-app-2">',
      '<span>fan-in: <b>', Number(node.fan_in) || 0, '</b></span>',
      '<span>fan-out: <b>', Number(node.fan_out) || 0, '</b></span>',
      node.layer ? ('<span>layer: <b>' + ESC(node.layer) + '</b></span>') : '',
      '</div></div>',
    ].join('');
  }

  // ---- Control bar ----
  function controlBarHtml(filters, nodeCount) {
    var btn = function (group, kind, set) {
      var on = set.has(kind) ? ' active' : '';
      return '<button class="g3d-filter-btn' + on + '" data-toggle="' + ESC(group)
        + '" data-kind="' + ESC(kind) + '">' + ESC(kind) + '</button>';
    };
    return [
      '<div class="g3d-controls">',
      '<div class="g3d-controls-group">',
      '<span class="g3d-controls-lbl">Kinds</span>',
      ALL_KINDS.map(function (k) { return btn('kind', k, filters.kinds); }).join(''),
      '</div>',
      '<div class="g3d-controls-sep"></div>',
      '<div class="g3d-controls-group">',
      '<span class="g3d-controls-lbl">Edges</span>',
      ALL_EDGES.map(function (k) { return btn('edge', k, filters.edgeKinds); }).join(''),
      '</div>',
      '<div class="g3d-controls-sep"></div>',
      '<div class="g3d-controls-group">',
      '<button class="g3d-filter-btn" id="g3d-demo-btn" title="Auto-rotate demo">Demo</button>',
      '<button class="g3d-filter-btn" id="g3d-reset-btn" title="Reset filters and camera">Reset</button>',
      '<span class="g3d-controls-lbl ml-auto">', Number(nodeCount) || 0, ' nodes</span>',
      '</div>',
      '</div>',
    ].join('');
  }

  // ---- Demo loop controller ----
  function DemoController(graph, nodes) {
    var self = this;
    self._raf = null;
    self._stopped = false;
    self._phase = 'rotate';
    self._phaseStart = performance.now();
    self._hotspot = null;
    if (nodes && nodes.length) {
      var top = nodes[0];
      for (var i = 1; i < nodes.length; i++) {
        if ((nodes[i].fan_in || 0) > (top.fan_in || 0)) top = nodes[i];
      }
      self._hotspot = top;
    }
    try { graph.controls().autoRotate = true; graph.controls().autoRotateSpeed = 0.6; }
    catch (e) { /* ignore */ }

    function tick() {
      if (self._stopped) return;
      var now = performance.now();
      var t = now - self._phaseStart;
      if (self._phase === 'rotate' && t > 2000 && self._hotspot) {
        self._phase = 'zoomIn';
        self._phaseStart = now;
        try { graph.controls().autoRotate = false; } catch (e) {}
        var n = self._hotspot;
        var dist = 180;
        var len = Math.hypot(n.x || 1, n.y || 1, n.z || 1) || 1;
        graph.cameraPosition(
          { x: (n.x || 0) * dist / len,
            y: (n.y || 0) * dist / len,
            z: (n.z || 0) * dist / len },
          { x: n.x || 0, y: n.y || 0, z: n.z || 0 },
          1500
        );
      } else if (self._phase === 'zoomIn' && t > 3500) {
        self._phase = 'zoomOut';
        self._phaseStart = now;
        graph.cameraPosition({ x: 0, y: 0, z: 600 }, { x: 0, y: 0, z: 0 }, 1500);
      } else if (self._phase === 'zoomOut' && t > 3000) {
        self._phase = 'rotate';
        self._phaseStart = now;
        try { graph.controls().autoRotate = true; } catch (e) {}
      }
      self._raf = requestAnimationFrame(tick);
    }
    self._raf = requestAnimationFrame(tick);

    self.destroy = function () {
      self._stopped = true;
      if (self._raf) cancelAnimationFrame(self._raf);
      try { graph.controls().autoRotate = false; } catch (e) {}
    };
  }

  function attachControls(host, hld, filters, container, detailEl) {
    host.querySelectorAll('.g3d-filter-btn[data-toggle]').forEach(function (btn) {
      btn.addEventListener('click', function () {
        var toggle = btn.dataset.toggle;
        var kind = btn.dataset.kind;
        var set = toggle === 'kind' ? filters.kinds : filters.edgeKinds;
        if (set.has(kind)) set.delete(kind); else set.add(kind);
        btn.classList.toggle('active');
        var data = getTransform().buildGraph3dData(hld, filters);
        if (instance) instance.graphData(data);
      });
    });
    var resetBtn = host.querySelector('#g3d-reset-btn');
    if (resetBtn) resetBtn.addEventListener('click', function () {
      lastFilters = defaultFilters();
      renderGraph3d(host);
    });
    var demoBtn = host.querySelector('#g3d-demo-btn');
    if (demoBtn) demoBtn.addEventListener('click', function () {
      location.href = location.pathname + '?demo=1#graph3d';
    });
  }

  function wireFallback(host) {
    if (window.lucide) window.lucide.createIcons();
    var btn = host.querySelector('#g3d-fallback-hld');
    if (btn && typeof window.activate === 'function') {
      btn.addEventListener('click', function () { window.activate('hld'); });
    }
  }

  function renderGraph3d(host) {
    teardown();

    var hld = (window.state && window.state.data && window.state.data.hld) || { modules: {} };
    var filters = lastFilters || defaultFilters();
    // Recover from a stuck "all filters off" state when the user returns
    // to the view after toggling everything off in a previous visit.
    if (filters.kinds.size === 0 && filters.edgeKinds.size === 0) {
      filters = defaultFilters();
    }
    lastFilters = filters;

    if (!hasWebGL()) {
      host.innerHTML = fallbackHtml('WebGL is not supported in this browser.');
      wireFallback(host);
      return;
    }

    host.innerHTML = [
      '<div class="p-6 max-w-7xl mx-auto">',
      '<div class="help-card mb-4">',
      '<i data-lucide="atom" class="icon w-4 h-4"></i>',
      '<div><b>3D force-directed graph.</b> Drag to orbit, scroll to zoom, click a node to focus. ',
      'Add <code>?demo=1</code> for an autoplay tour.</div>',
      '</div>',
      '<div id="g3d-controls-host"></div>',
      '<div class="g3d-canvas-wrap" id="g3d-canvas"></div>',
      '<div id="g3d-detail" class="mt-4"></div>',
      '</div>',
    ].join('');

    var data = getTransform().buildGraph3dData(hld, filters);
    var nodeCount = data.nodes.length;

    document.getElementById('g3d-controls-host').innerHTML =
      controlBarHtml(filters, nodeCount);
    if (window.lucide) window.lucide.createIcons();

    if (nodeCount === 0) {
      var empty = document.getElementById('g3d-canvas');
      empty.textContent = '';
      var msg = document.createElement('div');
      msg.className = 'g3d-empty';
      msg.textContent = 'No symbols match the current filters.';
      empty.appendChild(msg);
      attachControls(host, hld, filters, null, null);
      return;
    }

    if (nodeCount > DETAIL_THRESHOLD && window.toast) {
      window.toast('Large graph (' + nodeCount + ' nodes) — labels disabled for performance.', 'warn');
    }

    loadLibrary().then(function () {
      bootScene(host, hld, filters, data);
    }).catch(function () {
      host.innerHTML = fallbackHtml('3D Graph library failed to load.');
      wireFallback(host);
      if (window.toast) window.toast('3D graph library unavailable.', 'error');
    });
  }

  function bootScene(host, hld, filters, data) {
    var container = document.getElementById('g3d-canvas');
    if (!container || typeof window.ForceGraph3D === 'undefined') return;

    var detailEl = document.getElementById('g3d-detail');
    var nodeCount = data.nodes.length;
    var labelsOn = nodeCount < LABEL_THRESHOLD;

    try {
      instance = window.ForceGraph3D()(container)
        .backgroundColor(bgColor())
        .nodeRelSize(4)
        .nodeColor(function (n) { return n.color; })
        .nodeVal(function (n) { return n.val; })
        .nodeLabel(function (n) {
          return labelsOn
            ? '<div class="g3d-tip"><b>' + escapeBasic(n.name) + '</b><br>'
              + escapeBasic(n.kind) + ' · in ' + (Number(n.fan_in) || 0)
              + ' · out ' + (Number(n.fan_out) || 0) + '</div>'
            : '';
        })
        .linkColor(function (l) { return l.color; })
        .linkOpacity(nodeCount > DETAIL_THRESHOLD ? 0.15 : 0.4)
        .linkDirectionalParticles(nodeCount > DETAIL_THRESHOLD ? 0 : 1)
        .linkDirectionalParticleSpeed(0.005)
        .onNodeHover(function (node) {
          container.style.cursor = node ? 'pointer' : 'grab';
        })
        .onNodeClick(function (node) {
          if (!node) return;
          var dist = 100;
          var len = Math.hypot(node.x || 1, node.y || 1, node.z || 1) || 1;
          instance.cameraPosition(
            { x: node.x * (1 + dist / len),
              y: node.y * (1 + dist / len),
              z: node.z * (1 + dist / len) },
            node, 800
          );
          if (detailEl) detailEl.innerHTML = detailHtml(node);
        })
        .graphData(data);

      attachControls(host, hld, filters, container, detailEl);

      if (typeof ResizeObserver !== 'undefined') {
        resizeObs = new ResizeObserver(function () {
          if (instance && container.clientWidth) {
            instance.width(container.clientWidth).height(container.clientHeight);
          }
        });
        resizeObs.observe(container);
      }

      if (new URLSearchParams(location.search).get('demo') === '1') {
        demoCtl = new DemoController(instance, data.nodes);
      }
    } catch (e) {
      host.innerHTML = fallbackHtml('WebGL initialization failed: ' + (e && e.message || e));
      wireFallback(host);
    }
  }

  window.renderGraph3d = renderGraph3d;
})();
