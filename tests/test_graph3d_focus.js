/* Tests for buildFocusGraph — BFS-based focus-mode transform for the 3D
 * Graph view.
 *
 * Run with:  node --test tests/test_graph3d_focus.js
 */
'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');

const { buildFocusGraph, searchSymbols } = require(
  path.join(__dirname, '..', 'codegraph', 'web', 'static', 'views', 'graph3d_transform.js')
);

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
