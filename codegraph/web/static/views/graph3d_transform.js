/* graph3d_transform.js — pure data transform for the 3D Graph view.
 *
 * Loaded as a classic browser <script> AND as a CommonJS module under Node
 * for `node --test`. No DOM, no globals other than the optional
 * `module.exports` guard at the bottom.
 *
 * Inputs:
 *   hld      — state.data.hld (object with .modules)
 *   filters  — { kinds: Set<string>, edgeKinds: Set<string> }
 *
 * Output:
 *   { nodes: [...], links: [...] }
 *
 * Node shape:   { id, name, kind, file, language, layer, fan_in, fan_out, val, color }
 * Link shape:   { source, target, kind, color }
 */
'use strict';

// Color tokens — kept in sync with app.css custom properties / Tailwind config
// (see PLAN_3D_VIEW.md §3). Hex literals here so the file is theme-agnostic at
// transform time; the renderer applies a slight hue shift in light mode.
var KIND_COLORS = {
  FUNCTION: '#34d399', // emerald
  CLASS:    '#a78bfa', // violet
  METHOD:   '#22d3ee', // cyan
  MODULE:   '#818cf8', // brand
};
var KIND_FALLBACK = '#8b9ab8'; // ink-200

var EDGE_COLORS = {
  CALLS:      'rgba(129,140,248,0.5)',
  IMPORTS:    'rgba(34,211,238,0.4)',
  INHERITS:   'rgba(167,139,250,0.5)',
  IMPLEMENTS: 'rgba(167,139,250,0.5)',
};
var EDGE_FALLBACK = 'rgba(139,154,184,0.35)';

function kindColor(kind) {
  return KIND_COLORS[kind] || KIND_FALLBACK;
}

function edgeColor(kind) {
  return EDGE_COLORS[kind] || EDGE_FALLBACK;
}

function clampVal(fanIn) {
  var v = 2 + (Number(fanIn) || 0);
  if (v < 2) v = 2;
  if (v > 12) v = 12;
  return v;
}

function buildGraph3dData(hld, filters) {
  var modules = (hld && hld.modules) || {};
  var kinds = (filters && filters.kinds) || new Set();
  var edgeKinds = (filters && filters.edgeKinds) || new Set();

  var nodeMap = new Map();

  // 1. Emit nodes for each symbol whose kind passes the filter.
  Object.keys(modules).forEach(function (modQn) {
    var mod = modules[modQn] || {};
    var symbols = mod.symbols || [];
    symbols.forEach(function (sym) {
      if (!sym || !sym.qualname) return;
      if (!kinds.has(sym.kind)) return;
      nodeMap.set(sym.qualname, {
        id: sym.qualname,
        name: sym.name || sym.qualname,
        kind: sym.kind,
        file: mod.file || '',
        language: mod.language || '',
        layer: mod.layer || '',
        fan_in: Number(sym.fan_in) || 0,
        fan_out: Number(sym.fan_out) || 0,
        val: clampVal(sym.fan_in),
        color: kindColor(sym.kind),
      });
    });
  });

  // 2. Emit CALLS links from callers/callees, deduped per (src, dst).
  var links = [];
  if (edgeKinds.has('CALLS')) {
    var seen = new Set();
    Object.keys(modules).forEach(function (modQn) {
      var symbols = (modules[modQn] || {}).symbols || [];
      symbols.forEach(function (sym) {
        var srcId = sym.qualname;
        if (!nodeMap.has(srcId)) return;
        (sym.callees || []).forEach(function (dstId) {
          if (!nodeMap.has(dstId)) return;
          var key = srcId + '' + dstId;
          if (seen.has(key)) return;
          seen.add(key);
          links.push({
            source: srcId,
            target: dstId,
            kind: 'CALLS',
            color: edgeColor('CALLS'),
          });
        });
        (sym.callers || []).forEach(function (callerId) {
          if (!nodeMap.has(callerId)) return;
          var key = callerId + '' + srcId;
          if (seen.has(key)) return;
          seen.add(key);
          links.push({
            source: callerId,
            target: srcId,
            kind: 'CALLS',
            color: edgeColor('CALLS'),
          });
        });
      });
    });
  }

  return {
    nodes: Array.from(nodeMap.values()),
    links: links,
  };
}

// Browser global registration (when loaded via <script>).
if (typeof window !== 'undefined') {
  window.CG_Graph3DTransform = {
    buildGraph3dData: buildGraph3dData,
    kindColor: kindColor,
    edgeColor: edgeColor,
  };
}

// Node CommonJS export (when required from tests).
if (typeof module !== 'undefined' && module.exports) {
  module.exports = {
    buildGraph3dData: buildGraph3dData,
    kindColor: kindColor,
    edgeColor: edgeColor,
  };
}
