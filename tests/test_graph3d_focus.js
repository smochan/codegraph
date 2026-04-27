/* Tests for buildFocusGraph — BFS-based focus-mode transform for the 3D
 * Graph view.
 *
 * Run with:  node --test tests/test_graph3d_focus.js
 */
'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');

const T = require(
  path.join(__dirname, '..', 'codegraph', 'web', 'static', 'views', 'graph3d_transform.js')
);
const {
  buildFocusGraph, searchSymbols, isExternalQn, indexSymbols,
  makeFocusState, expandNode, collapseNode, isExpanded, snapshotState,
  groupSymbols, filterGrouped, formatCallArgs,
} = T;

// ---- Fixture builders ------------------------------------------------------

// Build a single-module HLD from a list of [qualname, callers[], callees[]]
// triples. All symbols are FUNCTION kind by default.
function hldFrom(rows, opts) {
  opts = opts || {};
  return {
    modules: {
      m: {
        qualname: 'm',
        file: 'm.py',
        layer: 'core',
        language: 'python',
        symbols: rows.map(function (r) {
          return {
            qualname: r[0],
            name: (opts.shortNames && r[0].split('.').pop()) || r[0],
            kind: r[3] || 'FUNCTION',
            fan_in: (r[1] || []).length,
            fan_out: (r[2] || []).length,
            callers: r[1] || [],
            callees: r[2] || [],
          };
        }),
      },
    },
  };
}

// ---- Tests -----------------------------------------------------------------

test('empty rootQn returns empty graph', () => {
  const hld = hldFrom([['m.a', [], []]]);
  const out = buildFocusGraph(hld, '', 2, 'both');
  assert.deepEqual(out.nodes, []);
  assert.deepEqual(out.links, []);
});

test('root not in HLD returns empty graph', () => {
  const hld = hldFrom([['m.a', [], []]]);
  const out = buildFocusGraph(hld, 'm.does_not_exist', 2, 'both');
  assert.deepEqual(out.nodes, []);
  assert.deepEqual(out.links, []);
});

test('isolated root returns one node, no links', () => {
  const hld = hldFrom([['m.solo', [], []]]);
  const out = buildFocusGraph(hld, 'm.solo', 2, 'both');
  assert.equal(out.nodes.length, 1);
  assert.equal(out.nodes[0].id, 'm.solo');
  assert.equal(out.nodes[0].role, 'root');
  assert.equal(out.nodes[0].depth, 0);
  assert.deepEqual(out.links, []);
});

test('linear chain a->b->c with root=b depth=1 yields 3 nodes', () => {
  const hld = hldFrom([
    ['m.a', [],         ['m.b']],
    ['m.b', ['m.a'],    ['m.c']],
    ['m.c', ['m.b'],    []],
  ]);
  const out = buildFocusGraph(hld, 'm.b', 1, 'both');
  const ids = out.nodes.map(n => n.id).sort();
  assert.deepEqual(ids, ['m.a', 'm.b', 'm.c']);
  // Roles
  const byId = Object.fromEntries(out.nodes.map(n => [n.id, n]));
  assert.equal(byId['m.b'].role, 'root');
  assert.equal(byId['m.a'].role, 'ancestor');
  assert.equal(byId['m.c'].role, 'descendant');
  // Edges directed: a->b (ancestor edge), b->c (descendant edge)
  const pairs = out.links.map(l => l.source + '->' + l.target).sort();
  assert.deepEqual(pairs, ['m.a->m.b', 'm.b->m.c']);
});

test('depth=2 picks up grandparents and grandchildren', () => {
  const hld = hldFrom([
    ['m.a', [],         ['m.b']],
    ['m.b', ['m.a'],    ['m.c']],
    ['m.c', ['m.b'],    ['m.d']],
    ['m.d', ['m.c'],    ['m.e']],
    ['m.e', ['m.d'],    []],
  ]);
  const out = buildFocusGraph(hld, 'm.c', 2, 'both');
  const ids = out.nodes.map(n => n.id).sort();
  assert.deepEqual(ids, ['m.a', 'm.b', 'm.c', 'm.d', 'm.e']);
  const byId = Object.fromEntries(out.nodes.map(n => [n.id, n]));
  assert.equal(byId['m.a'].depth, 2);
  assert.equal(byId['m.b'].depth, 1);
  assert.equal(byId['m.d'].depth, 1);
  assert.equal(byId['m.e'].depth, 2);
});

test('direction=ancestors returns no descendants', () => {
  const hld = hldFrom([
    ['m.a', [],         ['m.b']],
    ['m.b', ['m.a'],    ['m.c']],
    ['m.c', ['m.b'],    []],
  ]);
  const out = buildFocusGraph(hld, 'm.b', 2, 'ancestors');
  const ids = out.nodes.map(n => n.id).sort();
  assert.deepEqual(ids, ['m.a', 'm.b']);
  // No descendant role nodes
  assert.ok(!out.nodes.some(n => n.role === 'descendant'));
  // All edges should be ancestor-flavoured (caller -> here)
  assert.equal(out.links.length, 1);
  assert.equal(out.links[0].source, 'm.a');
  assert.equal(out.links[0].target, 'm.b');
});

test('direction=descendants returns no ancestors', () => {
  const hld = hldFrom([
    ['m.a', [],         ['m.b']],
    ['m.b', ['m.a'],    ['m.c']],
    ['m.c', ['m.b'],    []],
  ]);
  const out = buildFocusGraph(hld, 'm.b', 2, 'descendants');
  const ids = out.nodes.map(n => n.id).sort();
  assert.deepEqual(ids, ['m.b', 'm.c']);
  assert.ok(!out.nodes.some(n => n.role === 'ancestor'));
});

test('cycle in callers does not infinite-loop and dedupes', () => {
  // a -> b -> a (cycle). Use root=a, depth=4.
  const hld = hldFrom([
    ['m.a', ['m.b'], ['m.b']],
    ['m.b', ['m.a'], ['m.a']],
  ]);
  const out = buildFocusGraph(hld, 'm.a', 4, 'both');
  const ids = out.nodes.map(n => n.id).sort();
  assert.deepEqual(ids, ['m.a', 'm.b']);
  // No duplicate edges with same direction/role.
  const seen = new Set();
  for (const l of out.links) {
    const key = l.source + '->' + l.target + '/' + l.color;
    assert.ok(!seen.has(key), 'duplicate link emitted: ' + key);
    seen.add(key);
  }
});

test('role assignment: root=root, parents=ancestor, children=descendant', () => {
  const hld = hldFrom([
    ['m.parent', [],            ['m.root']],
    ['m.root',   ['m.parent'],  ['m.child']],
    ['m.child',  ['m.root'],    []],
  ]);
  const out = buildFocusGraph(hld, 'm.root', 1, 'both');
  const byId = Object.fromEntries(out.nodes.map(n => [n.id, n]));
  assert.equal(byId['m.root'].role, 'root');
  assert.equal(byId['m.parent'].role, 'ancestor');
  assert.equal(byId['m.child'].role, 'descendant');
  // Color assignment matches role tokens.
  assert.equal(byId['m.root'].color, '#a78bfa');
  assert.equal(byId['m.parent'].color, '#fbbf24');
  assert.equal(byId['m.child'].color, '#22d3ee');
});

test('edge colors follow role: ancestor edges amber, descendant edges cyan', () => {
  const hld = hldFrom([
    ['m.a', [],         ['m.b']],
    ['m.b', ['m.a'],    ['m.c']],
    ['m.c', ['m.b'],    []],
  ]);
  const out = buildFocusGraph(hld, 'm.b', 1, 'both');
  const byPair = Object.fromEntries(out.links.map(l => [l.source + '->' + l.target, l]));
  // a->b is the ancestor edge (caller -> here)
  assert.match(byPair['m.a->m.b'].color, /251,191,36/);
  // b->c is the descendant edge (here -> callee)
  assert.match(byPair['m.b->m.c'].color, /34,211,238/);
});

test('depth clamps below 1 to 1', () => {
  const hld = hldFrom([
    ['m.a', [],         ['m.b']],
    ['m.b', ['m.a'],    ['m.c']],
    ['m.c', ['m.b'],    []],
  ]);
  const out = buildFocusGraph(hld, 'm.b', 0, 'both');
  // depth=0 should still pull immediate neighbors (treated as 1)
  const ids = out.nodes.map(n => n.id).sort();
  assert.deepEqual(ids, ['m.a', 'm.b', 'm.c']);
});

test('searchSymbols ranks exact name match above substring match', () => {
  const hld = hldFrom([
    ['pkg.a.compute', [], []],
    ['pkg.b.precompute', [], []],
    ['pkg.c.compute_thing', [], []],
  ]);
  // Override module to multi-symbol layout
  const hits = searchSymbols(hld, 'compute', 10);
  assert.ok(hits.length >= 2);
  // The first hit should have name === 'compute' or qualname endswith compute
  assert.equal(hits[0].qualname, 'pkg.a.compute');
});

test('searchSymbols returns empty array for no matches', () => {
  const hld = hldFrom([['m.alpha', [], []]]);
  const hits = searchSymbols(hld, 'zzznever', 10);
  assert.deepEqual(hits, []);
});

test('searchSymbols with empty query returns top symbols by fan_in desc', () => {
  const hld = hldFrom([
    ['m.cold', [], []],
    ['m.hot',  ['m.a','m.b','m.c','m.d'], []],
    ['m.warm', ['m.a'], []],
  ]);
  const hits = searchSymbols(hld, '', 10);
  assert.equal(hits[0].qualname, 'm.hot');
});

// ---- Item 1: external-call filtering --------------------------------------

test('isExternalQn flags unresolved:: prefix and unknown qualnames', () => {
  const hld = hldFrom([['m.a', [], []]]);
  const idx = indexSymbols(hld);
  assert.equal(isExternalQn('unresolved::os.path.join', idx), true);
  assert.equal(isExternalQn('requests.get', idx), true);
  assert.equal(isExternalQn('m.a', idx), false);
  assert.equal(isExternalQn('', idx), true);
});

test('BFS does not traverse past external callees', () => {
  // m.a calls os.path.join (external) which "calls" m.deep — we should NOT
  // see m.deep because BFS stops at the external boundary.
  const hld = hldFrom([
    ['m.a', [], ['os.path.join']],
  ]);
  const out = buildFocusGraph(hld, 'm.a', 4, 'descendants');
  const ids = out.nodes.map(n => n.id).sort();
  assert.deepEqual(ids, ['m.a', 'os.path.join']);
  // External node has external: true and gray color.
  const ext = out.nodes.find(n => n.id === 'os.path.join');
  assert.equal(ext.external, true);
  assert.equal(ext.role, 'external');
  assert.equal(ext.color, '#8b9ab8');
  // Internal root is not flagged external.
  const root = out.nodes.find(n => n.id === 'm.a');
  assert.equal(root.external, false);
});

test('unresolved:: callees render as terminal external leaves', () => {
  const hld = hldFrom([
    ['m.a', [], ['unresolved::requests.get']],
  ]);
  const out = buildFocusGraph(hld, 'm.a', 2, 'descendants');
  const ext = out.nodes.find(n => n.qualname === 'unresolved::requests.get');
  assert.ok(ext, 'external leaf should be rendered');
  assert.equal(ext.external, true);
  assert.equal(ext.role, 'external');
  // Edge to external also flagged.
  const link = out.links.find(l => l.target === 'unresolved::requests.get');
  assert.ok(link);
  assert.equal(link.external, true);
});

// ---- Item 2: inline expand / collapse -------------------------------------

test('expandNode adds 1-hop neighbors of the clicked node', () => {
  const hld = hldFrom([
    ['m.root',  [],            ['m.child']],
    ['m.child', ['m.root'],    ['m.grand']],
    ['m.grand', ['m.child'],   []],
  ]);
  // Initial focus depth 1: only root + child shown.
  const state = makeFocusState(hld, 'm.root', 1, 'both');
  let snap = snapshotState(state);
  let ids = snap.nodes.map(n => n.id).sort();
  assert.deepEqual(ids, ['m.child', 'm.root']);
  // Expand child -> brings in m.grand (descendant of child).
  expandNode(state, hld, 'm.child');
  snap = snapshotState(state);
  ids = snap.nodes.map(n => n.id).sort();
  assert.deepEqual(ids, ['m.child', 'm.grand', 'm.root']);
  assert.equal(isExpanded(state, 'm.child'), true);
});

test('collapseNode removes only IDs added by that expansion (refcount)', () => {
  // shared neighbor: m.grand is a callee of both m.b1 and m.b2.
  // Expanding both adds m.grand twice (refcount=2). Collapsing m.b1
  // should NOT remove m.grand because m.b2 still references it.
  const hld = hldFrom([
    ['m.root', [],          ['m.b1', 'm.b2']],
    ['m.b1',   ['m.root'],  ['m.grand']],
    ['m.b2',   ['m.root'],  ['m.grand']],
    ['m.grand',['m.b1','m.b2'], []],
  ]);
  const state = makeFocusState(hld, 'm.root', 1, 'both');
  expandNode(state, hld, 'm.b1');
  expandNode(state, hld, 'm.b2');
  let ids = snapshotState(state).nodes.map(n => n.id).sort();
  assert.ok(ids.includes('m.grand'));
  assert.equal(state.refcount.get('m.grand'), 2);
  // Collapse b1: grand should still be present (refcount drops to 1).
  collapseNode(state, 'm.b1');
  ids = snapshotState(state).nodes.map(n => n.id).sort();
  assert.ok(ids.includes('m.grand'),
    'm.grand stays because m.b2 still expanded');
  assert.equal(state.refcount.get('m.grand'), 1);
  assert.equal(isExpanded(state, 'm.b1'), false);
  assert.equal(isExpanded(state, 'm.b2'), true);
  // Now collapse b2: grand is removed.
  collapseNode(state, 'm.b2');
  ids = snapshotState(state).nodes.map(n => n.id).sort();
  assert.ok(!ids.includes('m.grand'));
});

test('expand+collapse on a node with a cycle does not double-add or loop', () => {
  // m.a <-> m.b cycle. Expanding m.a should add m.b once even though
  // m.b is reachable both as callee and caller.
  const hld = hldFrom([
    ['m.root', [],         ['m.a']],
    ['m.a',    ['m.root'], ['m.b']],
    ['m.b',    ['m.a'],    ['m.a']],  // back-edge
  ]);
  const state = makeFocusState(hld, 'm.root', 1, 'both');
  // Expand m.a (which is in the initial graph).
  expandNode(state, hld, 'm.a');
  let snap = snapshotState(state);
  // No infinite loop, no duplicate node.
  const counts = {};
  snap.nodes.forEach(n => { counts[n.id] = (counts[n.id] || 0) + 1; });
  Object.keys(counts).forEach(id => {
    assert.equal(counts[id], 1, 'node ' + id + ' duplicated');
  });
  assert.ok(snap.nodes.some(n => n.id === 'm.b'));
  // Now collapse — m.b drops out, root and m.a stay.
  collapseNode(state, 'm.a');
  snap = snapshotState(state);
  const ids = snap.nodes.map(n => n.id).sort();
  assert.deepEqual(ids, ['m.a', 'm.root']);
});

test('expandNode is a no-op for the root and externals', () => {
  const hld = hldFrom([
    ['m.root', [], ['os.path']],
  ]);
  const state = makeFocusState(hld, 'm.root', 1, 'descendants');
  const before = snapshotState(state).nodes.length;
  expandNode(state, hld, 'm.root');
  expandNode(state, hld, 'os.path'); // external — has no entry in index
  const after = snapshotState(state).nodes.length;
  assert.equal(before, after);
});

test('external nodes do not bring their own callees into the graph', () => {
  // even if the external qn happened to also be in another module's callees
  // list, BFS should not expand from it.
  const hld = hldFrom([
    ['m.a',         [],         ['third.party.func']],
    ['m.deep_leaf', [],         []],
  ]);
  // mutate to give the (now external because not in index? it IS in index by qn —
  // actually third.party.func is NOT in the index, so external.) Confirm it
  // doesn't pull in m.deep_leaf even if somehow listed.
  const out = buildFocusGraph(hld, 'm.a', 5, 'descendants');
  const ids = out.nodes.map(n => n.id).sort();
  assert.ok(ids.includes('m.a'));
  assert.ok(ids.includes('third.party.func'));
  assert.ok(!ids.includes('m.deep_leaf'));
});

// ---- Item 4: grouped picker -----------------------------------------------

function multiModuleHld() {
  return {
    modules: {
      'pkg.a': {
        qualname: 'pkg.a',
        file: 'pkg/a.py',
        language: 'python',
        symbols: [
          { qualname: 'pkg.a.Foo',          name: 'Foo',     kind: 'CLASS',
            fan_in: 0, fan_out: 0, callers: [], callees: [] },
          { qualname: 'pkg.a.Foo.method1',  name: 'method1', kind: 'METHOD',
            fan_in: 1, fan_out: 0, callers: [], callees: [] },
          { qualname: 'pkg.a.Foo.method2',  name: 'method2', kind: 'METHOD',
            fan_in: 0, fan_out: 0, callers: [], callees: [] },
          { qualname: 'pkg.a.helper',       name: 'helper',  kind: 'FUNCTION',
            fan_in: 2, fan_out: 0, callers: [], callees: [] },
        ],
      },
      'pkg.b': {
        qualname: 'pkg.b',
        file: 'pkg/b.py',
        language: 'python',
        symbols: [
          { qualname: 'pkg.b.run', name: 'run', kind: 'FUNCTION',
            fan_in: 5, fan_out: 0, callers: [], callees: [] },
        ],
      },
    },
  };
}

test('groupSymbols returns module > class > methods, plus top-level functions', () => {
  const groups = groupSymbols(multiModuleHld());
  assert.equal(groups.length, 2);
  // First module pkg.a (alpha-sorted).
  const a = groups[0];
  assert.equal(a.qualname, 'pkg.a');
  assert.equal(a.classes.length, 1);
  assert.equal(a.classes[0].qualname, 'pkg.a.Foo');
  assert.deepEqual(
    a.classes[0].methods.map(m => m.name).sort(),
    ['method1', 'method2'],
  );
  assert.equal(a.functions.length, 1);
  assert.equal(a.functions[0].name, 'helper');
  // Second module pkg.b: just one function, no classes.
  const b = groups[1];
  assert.equal(b.qualname, 'pkg.b');
  assert.equal(b.classes.length, 0);
  assert.equal(b.functions.length, 1);
  assert.equal(b.functions[0].name, 'run');
});

test('filterGrouped keeps parent groups when nested method matches', () => {
  const groups = groupSymbols(multiModuleHld());
  const out = filterGrouped(groups, 'method1');
  // Should keep pkg.a (matching nested method) but drop pkg.b.
  assert.equal(out.length, 1);
  assert.equal(out[0].qualname, 'pkg.a');
  // The Foo class must remain because its nested method matched.
  assert.equal(out[0].classes.length, 1);
  assert.equal(out[0].classes[0].methods.length, 1);
  assert.equal(out[0].classes[0].methods[0].name, 'method1');
  // Top-level helper not matching is dropped.
  assert.equal(out[0].functions.length, 0);
});

test('filterGrouped with module-name match keeps all children', () => {
  const out = filterGrouped(groupSymbols(multiModuleHld()), 'pkg.b');
  assert.equal(out.length, 1);
  assert.equal(out[0].qualname, 'pkg.b');
  assert.equal(out[0].functions.length, 1);
});

// ---- DF0: edge arg labels --------------------------------------------------

test('formatCallArgs returns empty when both args and kwargs are empty/missing', () => {
  assert.equal(formatCallArgs({ args: [], kwargs: {} }), '');
  assert.equal(formatCallArgs({}), '');
  assert.equal(formatCallArgs(null), '');
  assert.equal(formatCallArgs(undefined), '');
});

test('formatCallArgs renders kwargs as key=value', () => {
  assert.equal(formatCallArgs({ args: ['1'], kwargs: { x: '2' } }), '1, x=2');
  assert.equal(formatCallArgs({ args: [], kwargs: { name: '"hi"' } }), 'name="hi"');
});

test('buildFocusGraph attaches argLabel to descendant edges from callee_args', () => {
  const hld = {
    modules: {
      'm': {
        qualname: 'm', file: 'm.py', language: 'python',
        symbols: [
          { qualname: 'm.a', name: 'a', kind: 'FUNCTION',
            fan_in: 0, fan_out: 1, callers: [], callees: ['m.b'],
            callee_args: [{ args: ['1'], kwargs: { x: '2' } }] },
          { qualname: 'm.b', name: 'b', kind: 'FUNCTION',
            fan_in: 1, fan_out: 0, callers: ['m.a'], callees: [] },
        ],
      },
    },
  };
  const out = buildFocusGraph(hld, 'm.a', 1, 'descendants');
  const link = out.links.find(l => l.target === 'm.b');
  assert.ok(link);
  assert.equal(link.argLabel, '1, x=2');
});

// ---- DF1.5: role-grouped picker -------------------------------------------

const { groupSymbolsByRole, ROLE_ORDER } = T;

function roleHld() {
  return {
    modules: {
      'app.api': {
        qualname: 'app.api', file: 'app/api.py', language: 'python',
        symbols: [
          { qualname: 'app.api.UserView', name: 'UserView', kind: 'CLASS',
            role: 'HANDLER', fan_in: 0, fan_out: 0, callers: [], callees: [] },
          { qualname: 'app.api.UserView.get', name: 'get', kind: 'METHOD',
            fan_in: 0, fan_out: 0, callers: [], callees: [] },
        ],
      },
      'app.svc': {
        qualname: 'app.svc', file: 'app/svc.py', language: 'python',
        symbols: [
          { qualname: 'app.svc.UserService', name: 'UserService', kind: 'CLASS',
            role: 'SERVICE', fan_in: 0, fan_out: 0, callers: [], callees: [] },
        ],
      },
      'app.repo': {
        qualname: 'app.repo', file: 'app/repo.py', language: 'python',
        symbols: [
          { qualname: 'app.repo.UserRepo', name: 'UserRepo', kind: 'CLASS',
            role: 'REPO', fan_in: 0, fan_out: 0, callers: [], callees: [] },
        ],
      },
      'app.ui': {
        qualname: 'app.ui', file: 'app/ui.py', language: 'python',
        symbols: [
          { qualname: 'app.ui.Card', name: 'Card', kind: 'CLASS',
            role: 'COMPONENT', fan_in: 0, fan_out: 0, callers: [], callees: [] },
        ],
      },
      'app.util': {
        qualname: 'app.util', file: 'app/util.py', language: 'python',
        symbols: [
          { qualname: 'app.util.helper', name: 'helper', kind: 'FUNCTION',
            fan_in: 0, fan_out: 0, callers: [], callees: [] },
        ],
      },
    },
  };
}

test('groupSymbolsByRole returns the 5 role buckets in fixed order', () => {
  const out = groupSymbolsByRole(roleHld());
  const roles = out.map(b => b.role);
  assert.deepEqual(roles, ['HANDLER', 'SERVICE', 'COMPONENT', 'REPO', '(no role)']);
  assert.deepEqual(roles, ROLE_ORDER);
  // Methods inherit class role: app.api.UserView.get goes under HANDLER.
  const handler = out[0];
  assert.equal(handler.modules.length, 1);
  assert.equal(handler.modules[0].qualname, 'app.api');
  assert.equal(handler.modules[0].classes.length, 1);
  assert.equal(handler.modules[0].classes[0].methods.length, 1);
});

test('symbols without role land in "(no role)" bucket', () => {
  const out = groupSymbolsByRole(roleHld());
  const noRole = out[out.length - 1];
  assert.equal(noRole.role, '(no role)');
  assert.equal(noRole.modules.length, 1);
  assert.equal(noRole.modules[0].qualname, 'app.util');
  assert.equal(noRole.modules[0].functions[0].name, 'helper');
});

test('groupSymbolsByRole handles role=null gracefully (no crash)', () => {
  const hld = {
    modules: {
      'm': {
        qualname: 'm', file: 'm.py', language: 'python',
        symbols: [
          { qualname: 'm.fn', name: 'fn', kind: 'FUNCTION', role: null,
            fan_in: 0, fan_out: 0, callers: [], callees: [] },
          { qualname: 'm.gn', name: 'gn', kind: 'FUNCTION',
            fan_in: 0, fan_out: 0, callers: [], callees: [] },
        ],
      },
    },
  };
  const out = groupSymbolsByRole(hld);
  const noRole = out.find(b => b.role === '(no role)');
  assert.ok(noRole);
  assert.equal(noRole.modules.length, 1);
  const fns = noRole.modules[0].functions.map(f => f.name).sort();
  assert.deepEqual(fns, ['fn', 'gn']);
});

// ---- DF0: signature formatting --------------------------------------------

const { formatSignature } = T;

test('formatSignature renders f(a: int, b: str = "x") -> bool', () => {
  const node = {
    name: 'f',
    params: [
      { name: 'a', type: 'int', default: null },
      { name: 'b', type: 'str', default: '"x"' },
    ],
    returns: 'bool',
  };
  assert.equal(formatSignature(node), 'f(a: int, b: str = "x") -> bool');
});

test('formatSignature omits ": type" when type is None', () => {
  const node = {
    name: 'g',
    params: [
      { name: 'x', type: null, default: null },
      { name: 'y', type: null, default: '0' },
    ],
    returns: 'int',
  };
  assert.equal(formatSignature(node), 'g(x, y = 0) -> int');
});

test('formatSignature omits "-> returns" when returns is None', () => {
  const node = {
    name: 'h',
    params: [{ name: 'x', type: 'int', default: null }],
    returns: null,
  };
  assert.equal(formatSignature(node), 'h(x: int)');
});

test('formatSignature returns empty string when no params and no returns', () => {
  assert.equal(formatSignature({ name: 'noop', params: [], returns: null }), '');
  assert.equal(formatSignature({ name: 'noop' }), '');
});
