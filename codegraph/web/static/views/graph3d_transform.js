/* graph3d_transform.js — pure data transforms for the 3D Graph view.
 *
 * Loaded as a classic browser <script> AND as a CommonJS module under Node
 * for `node --test`. No DOM, no globals other than the optional
 * `module.exports` guard at the bottom.
 *
 * Two transforms live here:
 *
 *   buildGraph3dData(hld, filters)
 *     Legacy "show everything matching filters" view. Kept for tests and
 *     future side-panel use; the focus-mode controller does NOT call it.
 *
 *   buildFocusGraph(hld, rootQn, depth, direction)
 *     BFS from rootQn over the per-symbol callers/callees adjacency in the
 *     HLD payload. Returns the same {nodes, links} shape, with a `role`
 *     field on each node ('root' | 'ancestor' | 'descendant') and edge
 *     colors keyed to the descendant role.
 *
 * Node shape:   { id, name, qualname, kind, file, language, layer,
 *                 fan_in, fan_out, role, depth, val, color }
 * Link shape:   { source, target, kind, color }
 */
'use strict';

// ---- Color tokens ----------------------------------------------------------

var KIND_COLORS = {
  FUNCTION: '#34d399', // emerald
  CLASS:    '#a78bfa', // violet
  METHOD:   '#22d3ee', // cyan
  MODULE:   '#818cf8', // brand
};
var KIND_FALLBACK = '#8b9ab8';

var EDGE_COLORS = {
  CALLS:      'rgba(129,140,248,0.5)',
  IMPORTS:    'rgba(34,211,238,0.4)',
  INHERITS:   'rgba(167,139,250,0.5)',
  IMPLEMENTS: 'rgba(167,139,250,0.5)',
};
var EDGE_FALLBACK = 'rgba(139,154,184,0.35)';

// Focus-mode role colors. The root pops violet, ancestors flow in amber
// and descendants flow out cyan. Edge color follows the descendant role
// so caller→root edges read amber and root→callee edges read cyan.
// External (stdlib / third-party) nodes render as gray-outline terminal
// leaves — visible at the boundary but never traversed.
var ROLE_COLORS = {
  root:        '#a78bfa', // violet
  ancestor:    '#fbbf24', // amber
  descendant:  '#22d3ee', // cyan
  external:    '#8b9ab8', // gray (terminal leaf)
};
var ROLE_EDGE_COLORS = {
  ancestor:    'rgba(251,191,36,0.55)',
  descendant:  'rgba(34,211,238,0.55)',
  external:    'rgba(139,154,184,0.35)',
};

function kindColor(kind) {
  return KIND_COLORS[kind] || KIND_FALLBACK;
}
function edgeColor(kind) {
  return EDGE_COLORS[kind] || EDGE_FALLBACK;
}
function roleColor(role) {
  return ROLE_COLORS[role] || KIND_FALLBACK;
}

function clampVal(fanIn) {
  var v = 2 + (Number(fanIn) || 0);
  if (v < 2) v = 2;
  if (v > 12) v = 12;
  return v;
}

// ---- Symbol index ----------------------------------------------------------

// Walk hld.modules once and return a map qualname -> { sym, modQn, mod }.
function indexSymbols(hld) {
  var modules = (hld && hld.modules) || {};
  var index = new Map();
  Object.keys(modules).forEach(function (modQn) {
    var mod = modules[modQn] || {};
    var symbols = mod.symbols || [];
    symbols.forEach(function (sym) {
      if (!sym || !sym.qualname) return;
      index.set(sym.qualname, { sym: sym, modQn: modQn, mod: mod });
    });
  });
  return index;
}

// ---- Legacy "show all" transform ------------------------------------------

function buildGraph3dData(hld, filters) {
  var modules = (hld && hld.modules) || {};
  var kinds = (filters && filters.kinds) || new Set();
  var edgeKinds = (filters && filters.edgeKinds) || new Set();

  var nodeMap = new Map();

  Object.keys(modules).forEach(function (modQn) {
    var mod = modules[modQn] || {};
    var symbols = mod.symbols || [];
    symbols.forEach(function (sym) {
      if (!sym || !sym.qualname) return;
      if (!kinds.has(sym.kind)) return;
      nodeMap.set(sym.qualname, {
        id: sym.qualname,
        name: sym.name || sym.qualname,
        qualname: sym.qualname,
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

// ---- Focus mode (BFS from a root) -----------------------------------------

function makeNode(entry, role, depth) {
  var sym = entry.sym;
  var mod = entry.mod;
  // Root pops larger; descendants/ancestors get a moderate boost.
  var baseVal = clampVal(sym.fan_in);
  if (role === 'root') baseVal = 8;
  return {
    id: sym.qualname,
    name: sym.name || sym.qualname,
    qualname: sym.qualname,
    kind: sym.kind,
    file: mod.file || '',
    language: mod.language || '',
    layer: mod.layer || '',
    fan_in: Number(sym.fan_in) || 0,
    fan_out: Number(sym.fan_out) || 0,
    role: role,
    depth: depth,
    val: baseVal,
    color: roleColor(role),
    external: false,
  };
}

// Build a synthetic node for an external (stdlib / third-party) symbol
// that the BFS doesn't expand. Pretty-print short name from the qualname.
function makeExternalNode(qn, depth) {
  var raw = String(qn || '');
  var clean = raw.indexOf('unresolved::') === 0 ? raw.slice('unresolved::'.length) : raw;
  var parts = clean.split('.');
  var short = parts[parts.length - 1] || clean;
  return {
    id: raw,
    name: short,
    qualname: raw,
    kind: 'EXTERNAL',
    file: '',
    language: '',
    layer: '',
    fan_in: 0,
    fan_out: 0,
    role: 'external',
    depth: depth,
    val: 3,
    color: ROLE_COLORS.external,
    external: true,
  };
}

// A qualname is "external" if it starts with `unresolved::` or it is not
// present in the symbol index built from hld.modules.
function isExternalQn(qn, index) {
  if (!qn) return true;
  if (String(qn).indexOf('unresolved::') === 0) return true;
  return !index.has(qn);
}

function buildFocusGraph(hld, rootQn, depth, direction) {
  if (!rootQn) return { nodes: [], links: [] };

  var maxDepth = Number(depth);
  if (!isFinite(maxDepth) || maxDepth < 1) maxDepth = 1;
  if (maxDepth > 8) maxDepth = 8;

  var dir = direction || 'both';

  var index = indexSymbols(hld);
  if (!index.has(rootQn)) return { nodes: [], links: [] };

  var nodes = new Map(); // qn -> node
  var links = [];
  var linkKeys = new Set();

  function addLink(source, target, role, external) {
    var key = source + '' + target + '' + role;
    if (linkKeys.has(key)) return;
    linkKeys.add(key);
    var edgeRole = external ? 'external' : role;
    links.push({
      source: source,
      target: target,
      kind: 'CALLS',
      color: ROLE_EDGE_COLORS[edgeRole] || EDGE_FALLBACK,
      external: !!external,
    });
  }

  // Seed with root.
  nodes.set(rootQn, makeNode(index.get(rootQn), 'root', 0));

  // Generic BFS that walks one direction. `step(qn) -> [neighbor qn]`
  // maps a node to its outgoing/incoming neighbors per direction.
  function bfs(role, step, edgeFromTo) {
    var frontier = [rootQn];
    var visited = new Set([rootQn]);
    for (var d = 1; d <= maxDepth; d++) {
      var next = [];
      for (var i = 0; i < frontier.length; i++) {
        var here = frontier[i];
        var neighbors = step(here);
        for (var j = 0; j < neighbors.length; j++) {
          var nb = neighbors[j];
          if (!nb) continue;
          var external = isExternalQn(nb, index);
          if (external) {
            // Terminal leaf: render once, never traverse.
            var fromToExt = edgeFromTo(here, nb);
            addLink(fromToExt[0], fromToExt[1], role, true);
            if (!nodes.has(nb)) {
              nodes.set(nb, makeExternalNode(nb, d));
            }
            continue;
          }
          // Emit the edge (even if neighbor was already visited via
          // another path — but dedup via linkKeys).
          var fromTo = edgeFromTo(here, nb);
          addLink(fromTo[0], fromTo[1], role, false);
          if (visited.has(nb)) continue;
          visited.add(nb);
          // Don't downgrade root if it shows up in a cycle.
          if (!nodes.has(nb)) {
            nodes.set(nb, makeNode(index.get(nb), role, d));
          }
          next.push(nb);
        }
      }
      if (next.length === 0) break;
      frontier = next;
    }
  }

  if (dir === 'ancestors' || dir === 'both') {
    bfs(
      'ancestor',
      function (qn) { return (index.get(qn).sym.callers || []); },
      function (here, nb) { return [nb, here]; } // caller -> here
    );
  }
  if (dir === 'descendants' || dir === 'both') {
    bfs(
      'descendant',
      function (qn) { return (index.get(qn).sym.callees || []); },
      function (here, nb) { return [here, nb]; } // here -> callee
    );
  }

  return {
    nodes: Array.from(nodes.values()),
    links: links,
  };
}

// ---- Symbol search (top-N matches) ----------------------------------------

function searchSymbols(hld, query, limit) {
  var max = Number(limit) || 20;
  var q = String(query || '').trim().toLowerCase();
  var modules = (hld && hld.modules) || {};
  var results = [];

  Object.keys(modules).forEach(function (modQn) {
    var mod = modules[modQn] || {};
    var symbols = mod.symbols || [];
    symbols.forEach(function (sym) {
      if (!sym || !sym.qualname) return;
      var qn = String(sym.qualname).toLowerCase();
      var nm = String(sym.name || '').toLowerCase();
      var score = -1;
      if (!q) {
        // No query: surface high-fan-in symbols first.
        score = 1000 - (Number(sym.fan_in) || 0);
      } else if (qn === q || nm === q) {
        score = 0;
      } else if (nm.startsWith(q)) {
        score = 1;
      } else if (qn.indexOf(q) !== -1) {
        score = 2 + qn.indexOf(q);
      } else if (nm.indexOf(q) !== -1) {
        score = 50 + nm.indexOf(q);
      } else {
        return;
      }
      results.push({
        qualname: sym.qualname,
        name: sym.name || sym.qualname,
        kind: sym.kind,
        file: mod.file || '',
        fan_in: Number(sym.fan_in) || 0,
        fan_out: Number(sym.fan_out) || 0,
        _score: score,
      });
    });
  });

  results.sort(function (a, b) {
    if (a._score !== b._score) return a._score - b._score;
    // Tie-break: higher fan_in first, then qualname asc.
    if (a.fan_in !== b.fan_in) return b.fan_in - a.fan_in;
    return a.qualname < b.qualname ? -1 : 1;
  });

  return results.slice(0, max).map(function (r) {
    delete r._score;
    return r;
  });
}

// ---- Exports --------------------------------------------------------------

if (typeof window !== 'undefined') {
  window.CG_Graph3DTransform = {
    buildGraph3dData: buildGraph3dData,
    buildFocusGraph: buildFocusGraph,
    searchSymbols: searchSymbols,
    isExternalQn: isExternalQn,
    indexSymbols: indexSymbols,
    kindColor: kindColor,
    edgeColor: edgeColor,
    roleColor: roleColor,
  };
}

if (typeof module !== 'undefined' && module.exports) {
  module.exports = {
    buildGraph3dData: buildGraph3dData,
    buildFocusGraph: buildFocusGraph,
    searchSymbols: searchSymbols,
    isExternalQn: isExternalQn,
    indexSymbols: indexSymbols,
    kindColor: kindColor,
    edgeColor: edgeColor,
    roleColor: roleColor,
  };
}
