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

// ---- Call-arg label (Change 2 / DF0) ---------------------------------------
//
// Format a single edge's args+kwargs into a short label.
//   args=[1], kwargs={x:2}  -> "1, x=2"
//   args=[],  kwargs={}     -> ""
//   missing                 -> ""
function formatCallArgs(callArg) {
  if (!callArg || typeof callArg !== 'object') return '';
  var parts = [];
  var args = Array.isArray(callArg.args) ? callArg.args : [];
  args.forEach(function (a) {
    if (a === null || a === undefined) return;
    var s = String(a);
    if (s.length) parts.push(s);
  });
  var kwargs = (callArg.kwargs && typeof callArg.kwargs === 'object') ? callArg.kwargs : {};
  Object.keys(kwargs).forEach(function (k) {
    var v = kwargs[k];
    parts.push(String(k) + '=' + String(v == null ? '' : v));
  });
  return parts.join(', ');
}

// Build a map: callee qualname -> argLabel from a symbol's parallel
// callees / callee_args arrays. Older payloads without callee_args
// yield an empty map.
function callArgsFromSym(sym) {
  var out = {};
  if (!sym) return out;
  var callees = sym.callees || [];
  var callArgs = sym.callee_args || [];
  for (var i = 0; i < callees.length; i++) {
    var label = formatCallArgs(callArgs[i]);
    if (label) out[callees[i]] = label;
  }
  return out;
}

// ---- Signature formatting (Change 4 / DF0) ---------------------------------
//
// Render a function's signature as a single line:
//   f(a: int, b: str = "x") -> bool
// Skip ": type" if type is None/missing; skip "= default" if missing;
// skip "-> returns" if returns is None/missing. Returns '' when params is
// empty AND returns is missing — the caller suppresses the entire block.
function formatSignature(node) {
  if (!node) return '';
  var name = node.name || '';
  var params = Array.isArray(node.params) ? node.params : [];
  var returns = node.returns;
  var hasParams = params.length > 0;
  var hasReturns = returns != null && String(returns).length > 0;
  if (!hasParams && !hasReturns) return '';
  var parts = params.map(function (p) {
    if (!p || !p.name) return '';
    var s = String(p.name);
    if (p.type != null && String(p.type).length) s += ': ' + String(p.type);
    if (p.default != null && String(p.default).length) s += ' = ' + String(p.default);
    return s;
  }).filter(function (s) { return s; });
  var sig = String(name) + '(' + parts.join(', ') + ')';
  if (hasReturns) sig += ' -> ' + String(returns);
  return sig;
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
    // DF0 enrichment — fall back gracefully on older payloads.
    params: Array.isArray(sym.params) ? sym.params : [],
    returns: sym.returns != null ? sym.returns : null,
    symbolRole: sym.role || null,
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

// A node belongs to test code if its qualname or file matches a common
// test convention. Drives the "Hide tests" toggle in the 3D view, since
// most users want to see real-code call chains by default and only opt
// into test fan-in when debugging coverage.
//
// Heuristics (intentionally conservative — false negatives over noise):
//  - qualname starts with `tests.` or `test.`
//  - qualname segment-bounded `tests` (e.g. `pkg.tests.foo`)
//  - file path under a tests/ directory
//  - filename matches Python (test_*.py, *_test.py), JS/TS (*.test.[jt]sx?,
//    *.spec.[jt]sx?), or Go (*_test.go) test conventions
var TEST_QN_RE = /(^|\.)(tests?)(\.|$)/i;
var TEST_FILE_RE = new RegExp(
  // tests/ directory anywhere
  '(^|/)tests?/' +
  // OR Python test_* / _test files
  '|(^|/)test_[^/]+\\.py$|_test\\.py$' +
  // OR JS/TS *.test.* / *.spec.*
  '|\\.(test|spec)\\.[jt]sx?$' +
  // OR Go *_test.go
  '|_test\\.go$',
  'i'
);

function isTestNode(qualname, file) {
  if (qualname && TEST_QN_RE.test(String(qualname))) return true;
  if (file && TEST_FILE_RE.test(String(file))) return true;
  return false;
}

function buildFocusGraph(hld, rootQn, depth, direction, opts) {
  if (!rootQn) return { nodes: [], links: [] };

  var maxDepth = Number(depth);
  if (!isFinite(maxDepth) || maxDepth < 1) maxDepth = 1;
  if (maxDepth > 8) maxDepth = 8;

  var dir = direction || 'both';
  var hideTests = !!(opts && opts.hideTests);

  var index = indexSymbols(hld);
  if (!index.has(rootQn)) return { nodes: [], links: [] };

  // The root itself is never filtered: if the user explicitly searched
  // for a test function, they want to see it.
  function shouldSkipNeighbor(qn) {
    if (!hideTests || qn === rootQn) return false;
    var entry = index.get(qn);
    var file = entry ? (entry.sym && entry.sym.file) || (entry.mod && entry.mod.file) || '' : '';
    return isTestNode(qn, file);
  }

  var nodes = new Map(); // qn -> node
  var links = [];
  var linkKeys = new Set();

  function addLink(source, target, role, external, argLabel) {
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
      argLabel: argLabel || '',
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
        // For descendant edges, args live on `here.callees`. For ancestor
        // edges, args live on the neighbor's callees pointing at `here`.
        var hereEntry = index.get(here);
        var hereCallArgs = (role === 'descendant' && hereEntry)
          ? callArgsFromSym(hereEntry.sym) : {};
        for (var j = 0; j < neighbors.length; j++) {
          var nb = neighbors[j];
          if (!nb) continue;
          if (shouldSkipNeighbor(nb)) continue;
          var external = isExternalQn(nb, index);
          var argLabel = '';
          if (role === 'descendant') {
            argLabel = hereCallArgs[nb] || '';
          } else if (role === 'ancestor') {
            var nbEntry = index.get(nb);
            if (nbEntry) {
              argLabel = callArgsFromSym(nbEntry.sym)[here] || '';
            }
          }
          if (external) {
            // Terminal leaf: render once, never traverse.
            var fromToExt = edgeFromTo(here, nb);
            addLink(fromToExt[0], fromToExt[1], role, true, argLabel);
            if (!nodes.has(nb)) {
              nodes.set(nb, makeExternalNode(nb, d));
            }
            continue;
          }
          // Emit the edge (even if neighbor was already visited via
          // another path — but dedup via linkKeys).
          var fromTo = edgeFromTo(here, nb);
          addLink(fromTo[0], fromTo[1], role, false, argLabel);
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

// ---- Inline expand / collapse ---------------------------------------------
//
// expandNode(state, hld, qn) and collapseNode(state, qn) mutate a graph
// state object in place:
//
//   state = {
//     nodes: Map<qn, node>,
//     links: Array<{source, target, kind, color, external}>,
//     linkKeys: Set<string>,    // dedup key
//     refcount: Map<qn, number>,  // node refcount (>= 1 while present)
//     expansions: Map<qn, {addedNodes: Set<qn>, addedLinkKeys: Set<string>}>,
//   }
//
// The graph state lives in the controller (graph3d.js); these helpers are
// pure transforms over it so we can unit-test the expand/collapse logic
// without touching the DOM.

function makeFocusState(hld, rootQn, depth, direction, opts) {
  var graph = buildFocusGraph(hld, rootQn, depth, direction, opts);
  var nodes = new Map();
  var refcount = new Map();
  graph.nodes.forEach(function (n) {
    nodes.set(n.id, n);
    refcount.set(n.id, 1);
  });
  var linkKeys = new Set();
  var links = [];
  graph.links.forEach(function (l) {
    var key = linkKey(l.source, l.target);
    if (linkKeys.has(key)) return;
    linkKeys.add(key);
    links.push(l);
  });
  return {
    rootQn: rootQn,
    nodes: nodes,
    links: links,
    linkKeys: linkKeys,
    refcount: refcount,
    expansions: new Map(),
  };
}

function linkKey(source, target) {
  var s = (source && source.id) || source;
  var t = (target && target.id) || target;
  return String(s) + '->' + String(t);
}

function snapshotState(state) {
  return { nodes: Array.from(state.nodes.values()), links: state.links.slice() };
}

// Expand: bring 1-hop neighbors of qn into the graph.
// External neighbors render as terminal leaves; internals get a role
// matching the relationship to qn (callers => ancestor, callees => descendant).
function expandNode(state, hld, qn, opts) {
  if (!state || !qn) return state;
  if (state.expansions.has(qn)) return state; // already expanded
  if (qn === state.rootQn) return state;

  var index = indexSymbols(hld);
  if (!index.has(qn)) return state;

  var hideTests = !!(opts && opts.hideTests);
  var entry = index.get(qn);
  var sym = entry.sym;
  var addedNodes = new Set();
  var addedLinkKeys = new Set();

  function shouldSkipNeighbor(neighborQn) {
    if (!hideTests || neighborQn === state.rootQn) return false;
    var nbEntry = index.get(neighborQn);
    var file = nbEntry ? (nbEntry.sym && nbEntry.sym.file) || (nbEntry.mod && nbEntry.mod.file) || '' : '';
    return isTestNode(neighborQn, file);
  }

  function addLeaf(neighborQn, role, edgePair, argLabel) {
    if (!neighborQn) return;
    var external = isExternalQn(neighborQn, index);
    var key = linkKey(edgePair[0], edgePair[1]);
    if (!state.linkKeys.has(key)) {
      state.linkKeys.add(key);
      addedLinkKeys.add(key);
      var edgeRole = external ? 'external' : role;
      state.links.push({
        source: edgePair[0],
        target: edgePair[1],
        kind: 'CALLS',
        color: ROLE_EDGE_COLORS[edgeRole] || EDGE_FALLBACK,
        external: external,
        argLabel: argLabel || '',
      });
    }
    if (state.nodes.has(neighborQn)) {
      // Bump refcount; another expansion already brought it in.
      state.refcount.set(neighborQn, (state.refcount.get(neighborQn) || 0) + 1);
      addedNodes.add(neighborQn);
      return;
    }
    var node;
    if (external) {
      node = makeExternalNode(neighborQn, 1);
    } else {
      node = makeNode(index.get(neighborQn), role, 1);
    }
    state.nodes.set(neighborQn, node);
    state.refcount.set(neighborQn, 1);
    addedNodes.add(neighborQn);
  }

  // Descendant edges carry args from this symbol's callee_args.
  // Ancestor edges (caller -> qn) carry args from the caller's
  // own callee_args list pointing at qn.
  var ownCallArgs = callArgsFromSym(sym);
  (sym.callers || []).forEach(function (c) {
    if (shouldSkipNeighbor(c)) return;
    var cEntry = index.get(c);
    var argLabel = '';
    if (cEntry) argLabel = callArgsFromSym(cEntry.sym)[qn] || '';
    addLeaf(c, 'ancestor', [c, qn], argLabel);
  });
  (sym.callees || []).forEach(function (c) {
    if (shouldSkipNeighbor(c)) return;
    addLeaf(c, 'descendant', [qn, c], ownCallArgs[c] || '');
  });

  state.expansions.set(qn, { addedNodes: addedNodes, addedLinkKeys: addedLinkKeys });
  return state;
}

// Collapse: undo a previous expand. Decrement refcounts of nodes added
// by this expansion; nodes whose refcount drops to 0 are removed. Edges
// added by this expansion are always removed.
function collapseNode(state, qn) {
  if (!state || !qn) return state;
  var rec = state.expansions.get(qn);
  if (!rec) return state;
  // Drop edges this expansion added.
  state.links = state.links.filter(function (l) {
    var key = linkKey(l.source, l.target);
    if (rec.addedLinkKeys.has(key)) {
      state.linkKeys.delete(key);
      return false;
    }
    return true;
  });
  // Decrement refcounts; remove orphaned nodes.
  rec.addedNodes.forEach(function (id) {
    var rc = (state.refcount.get(id) || 0) - 1;
    if (rc <= 0) {
      state.refcount.delete(id);
      state.nodes.delete(id);
    } else {
      state.refcount.set(id, rc);
    }
  });
  state.expansions.delete(qn);
  return state;
}

function isExpanded(state, qn) {
  return !!(state && state.expansions && state.expansions.has(qn));
}

// ---- Grouped picker (Item 4) ----------------------------------------------
//
// groupSymbols(hld) returns a list of modules. Each module contains:
//   { qualname, file, language, classes: [...], functions: [...] }
// Each class:
//   { qualname, name, methods: [{qualname, name, kind, fan_in, fan_out}] }
// Each function (top-level):
//   { qualname, name, kind, fan_in, fan_out }
//
// The shape is intentionally flat-but-grouped so the picker can render it
// as a tree: module -> class -> method, plus module-level functions.

function groupSymbols(hld) {
  var modules = (hld && hld.modules) || {};
  var out = [];
  Object.keys(modules).sort().forEach(function (modQn) {
    var mod = modules[modQn] || {};
    var symbols = mod.symbols || [];
    var classes = {}; // qn -> class entry
    var functions = [];
    var methodOwners = {}; // method qn -> class qn

    // First pass: seed classes (CLASS kind).
    symbols.forEach(function (s) {
      if (!s || !s.qualname) return;
      if (s.kind === 'CLASS') {
        classes[s.qualname] = {
          qualname: s.qualname,
          name: s.name || s.qualname,
          methods: [],
        };
      }
    });

    // Second pass: assign methods to their class by qualname prefix.
    symbols.forEach(function (s) {
      if (!s || !s.qualname || s.kind === 'CLASS') return;
      var meta = {
        qualname: s.qualname,
        name: s.name || s.qualname,
        kind: s.kind,
        fan_in: Number(s.fan_in) || 0,
        fan_out: Number(s.fan_out) || 0,
      };
      // Find owning class: longest prefix s.qualname.startsWith(classQn + '.')
      var owner = null;
      Object.keys(classes).forEach(function (cqn) {
        if (s.qualname.indexOf(cqn + '.') === 0) {
          if (!owner || cqn.length > owner.length) owner = cqn;
        }
      });
      if (owner) {
        classes[owner].methods.push(meta);
        methodOwners[s.qualname] = owner;
      } else {
        functions.push(meta);
      }
    });

    // Sort: classes alpha by name, methods alpha, functions alpha.
    var classList = Object.keys(classes).sort().map(function (k) {
      var c = classes[k];
      c.methods.sort(function (a, b) { return a.name.localeCompare(b.name); });
      return c;
    });
    functions.sort(function (a, b) { return a.name.localeCompare(b.name); });

    out.push({
      qualname: modQn,
      file: mod.file || '',
      language: mod.language || '',
      classes: classList,
      functions: functions,
    });
  });
  return out;
}

// Filter a grouped tree by query — keeps modules/classes that contain a
// match, plus the matching leaves themselves.
function filterGrouped(groups, query) {
  var q = String(query || '').trim().toLowerCase();
  if (!q) return groups;

  function matches(text) {
    return String(text || '').toLowerCase().indexOf(q) !== -1;
  }

  var out = [];
  groups.forEach(function (g) {
    var keptClasses = [];
    g.classes.forEach(function (c) {
      var keptMethods = c.methods.filter(function (m) {
        return matches(m.name) || matches(m.qualname);
      });
      var classMatches = matches(c.name) || matches(c.qualname);
      if (keptMethods.length || classMatches) {
        keptClasses.push({
          qualname: c.qualname,
          name: c.name,
          methods: classMatches ? c.methods : keptMethods,
        });
      }
    });
    var keptFns = g.functions.filter(function (f) {
      return matches(f.name) || matches(f.qualname);
    });
    var moduleMatches = matches(g.qualname);
    if (keptClasses.length || keptFns.length || moduleMatches) {
      out.push({
        qualname: g.qualname,
        file: g.file,
        language: g.language,
        classes: moduleMatches ? g.classes : keptClasses,
        functions: moduleMatches ? g.functions : keptFns,
      });
    }
  });
  return out;
}

// ---- Role-grouped picker (Change 3 / DF1.5) -------------------------------
//
// groupSymbolsByRole(hld) -> [
//   { role: 'HANDLER',  color: '#fbbf24', modules: [<group>] },
//   { role: 'SERVICE',  color: '#3b82f6', modules: [...] },
//   { role: 'COMPONENT',color: '#34d399', modules: [...] },
//   { role: 'REPO',     color: '#c084fc', modules: [...] },
//   { role: '(no role)',color: '#8b9ab8', modules: [...] },
// ]
// Each <group> has the same shape as groupSymbols() emits, but only the
// symbols matching the bucket role are retained. Methods inherit their
// class's role; free functions use their own role; symbols without a
// recognized role land in the "(no role)" bucket. Buckets render in fixed
// order so the picker UI has stable headers even when a bucket is empty.

var ROLE_ORDER = ['HANDLER', 'SERVICE', 'COMPONENT', 'REPO', '(no role)'];
var ROLE_PICKER_COLORS = {
  'HANDLER':   '#fbbf24', // amber
  'SERVICE':   '#3b82f6', // blue
  'COMPONENT': '#34d399', // green
  'REPO':      '#c084fc', // purple-pink
  '(no role)': '#8b9ab8', // gray
};

function normalizeRole(role) {
  if (!role) return '(no role)';
  var r = String(role).toUpperCase();
  if (ROLE_PICKER_COLORS[r]) return r;
  return '(no role)';
}

function groupSymbolsByRole(hld) {
  var modules = (hld && hld.modules) || {};
  var buckets = {};
  ROLE_ORDER.forEach(function (r) { buckets[r] = {}; });

  function getModule(role, modQn, mod) {
    if (!buckets[role][modQn]) {
      buckets[role][modQn] = {
        qualname: modQn,
        file: mod.file || '',
        language: mod.language || '',
        classes: {},
        functions: [],
      };
    }
    return buckets[role][modQn];
  }

  Object.keys(modules).forEach(function (modQn) {
    var mod = modules[modQn] || {};
    var symbols = mod.symbols || [];
    var classByQn = {};
    symbols.forEach(function (s) {
      if (s && s.kind === 'CLASS' && s.qualname) classByQn[s.qualname] = s;
    });

    symbols.forEach(function (s) {
      if (!s || !s.qualname) return;
      // Methods inherit their class's role.
      var ownerClass = null;
      if (s.kind !== 'CLASS') {
        Object.keys(classByQn).forEach(function (cqn) {
          if (s.qualname.indexOf(cqn + '.') === 0) {
            if (!ownerClass || cqn.length > ownerClass.qualname.length) {
              ownerClass = classByQn[cqn];
            }
          }
        });
      }
      var roleSrc = ownerClass ? (ownerClass.role || s.role) : s.role;
      var role = normalizeRole(roleSrc);
      var modEntry = getModule(role, modQn, mod);
      var meta = {
        qualname: s.qualname,
        name: s.name || s.qualname,
        kind: s.kind,
        fan_in: Number(s.fan_in) || 0,
        fan_out: Number(s.fan_out) || 0,
      };
      if (s.kind === 'CLASS') {
        if (!modEntry.classes[s.qualname]) {
          modEntry.classes[s.qualname] = {
            qualname: s.qualname,
            name: s.name || s.qualname,
            methods: [],
          };
        }
      } else if (ownerClass) {
        if (!modEntry.classes[ownerClass.qualname]) {
          modEntry.classes[ownerClass.qualname] = {
            qualname: ownerClass.qualname,
            name: ownerClass.name || ownerClass.qualname,
            methods: [],
          };
        }
        modEntry.classes[ownerClass.qualname].methods.push(meta);
      } else {
        modEntry.functions.push(meta);
      }
    });
  });

  return ROLE_ORDER.map(function (role) {
    var modMap = buckets[role];
    var modList = Object.keys(modMap).sort().map(function (mqn) {
      var m = modMap[mqn];
      var classList = Object.keys(m.classes).sort().map(function (k) {
        var c = m.classes[k];
        c.methods.sort(function (a, b) { return a.name.localeCompare(b.name); });
        return c;
      });
      m.functions.sort(function (a, b) { return a.name.localeCompare(b.name); });
      return {
        qualname: m.qualname,
        file: m.file,
        language: m.language,
        classes: classList,
        functions: m.functions,
      };
    });
    return {
      role: role,
      color: ROLE_PICKER_COLORS[role],
      modules: modList,
    };
  });
}

// Filter a role-grouped tree by query, keeping role buckets that contain
// at least one match. Reuses filterGrouped() per bucket.
function filterGroupedByRole(roleGroups, query) {
  var q = String(query || '').trim();
  if (!q) return roleGroups;
  return roleGroups.map(function (rg) {
    return {
      role: rg.role,
      color: rg.color,
      modules: filterGrouped(rg.modules, q),
    };
  });
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
    makeFocusState: makeFocusState,
    expandNode: expandNode,
    collapseNode: collapseNode,
    isExpanded: isExpanded,
    snapshotState: snapshotState,
    searchSymbols: searchSymbols,
    groupSymbols: groupSymbols,
    groupSymbolsByRole: groupSymbolsByRole,
    filterGrouped: filterGrouped,
    filterGroupedByRole: filterGroupedByRole,
    formatCallArgs: formatCallArgs,
    formatSignature: formatSignature,
    ROLE_ORDER: ROLE_ORDER,
    ROLE_PICKER_COLORS: ROLE_PICKER_COLORS,
    isExternalQn: isExternalQn,
    isTestNode: isTestNode,
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
    makeFocusState: makeFocusState,
    expandNode: expandNode,
    collapseNode: collapseNode,
    isExpanded: isExpanded,
    snapshotState: snapshotState,
    searchSymbols: searchSymbols,
    groupSymbols: groupSymbols,
    groupSymbolsByRole: groupSymbolsByRole,
    filterGrouped: filterGrouped,
    filterGroupedByRole: filterGroupedByRole,
    formatCallArgs: formatCallArgs,
    formatSignature: formatSignature,
    ROLE_ORDER: ROLE_ORDER,
    ROLE_PICKER_COLORS: ROLE_PICKER_COLORS,
    isExternalQn: isExternalQn,
    isTestNode: isTestNode,
    indexSymbols: indexSymbols,
    kindColor: kindColor,
    edgeColor: edgeColor,
    roleColor: roleColor,
  };
}
