/* Tests for buildGraph3dData — pure transform from hld.modules to
 * { nodes, links } for the 3D force-graph view.
 *
 * Run with:  node --test tests/test_graph3d_transform.js
 */
'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');

// The transform module is a classic browser script. We load it via a small
// shim so it exposes buildGraph3dData on module.exports when run under Node.
const { buildGraph3dData, kindColor, edgeColor } = require(
  path.join(__dirname, '..', 'codegraph', 'web', 'static', 'views', 'graph3d_transform.js')
);

const ALL_KINDS = new Set(['FUNCTION', 'METHOD', 'CLASS', 'MODULE']);
const ALL_EDGES = new Set(['CALLS', 'IMPORTS', 'INHERITS', 'IMPLEMENTS']);

function defaultFilters(over) {
  return Object.assign(
    { kinds: ALL_KINDS, edgeKinds: ALL_EDGES },
    over || {},
  );
}

test('empty hld yields empty graph', () => {
  const out = buildGraph3dData({ modules: {} }, defaultFilters());
  assert.deepEqual(out.nodes, []);
  assert.deepEqual(out.links, []);
});

test('missing modules key is tolerated', () => {
  const out = buildGraph3dData({}, defaultFilters());
  assert.deepEqual(out.nodes, []);
  assert.deepEqual(out.links, []);
});

test('one FUNCTION symbol produces one node with computed val', () => {
  const hld = {
    modules: {
      'pkg.mod': {
        qualname: 'pkg.mod', file: 'pkg/mod.py', layer: 'core', language: 'python',
        symbols: [
          { qualname: 'pkg.mod.foo', name: 'foo', kind: 'FUNCTION',
            fan_in: 3, fan_out: 0, line: 1, callers: [], callees: [] },
        ],
      },
    },
  };
  const out = buildGraph3dData(hld, defaultFilters());
  assert.equal(out.nodes.length, 1);
  const n = out.nodes[0];
  assert.equal(n.id, 'pkg.mod.foo');
  assert.equal(n.kind, 'FUNCTION');
  assert.equal(n.file, 'pkg/mod.py');
  assert.equal(n.layer, 'core');
  // val = max(2, min(12, 2 + fan_in)) = 5
  assert.equal(n.val, 5);
  assert.deepEqual(out.links, []);
});

test('val is clamped to [2, 12]', () => {
  const hld = {
    modules: {
      m: {
        qualname: 'm', file: 'm.py', symbols: [
          { qualname: 'm.cold', name: 'cold', kind: 'FUNCTION',
            fan_in: 0, fan_out: 0, callers: [], callees: [] },
          { qualname: 'm.hot', name: 'hot', kind: 'FUNCTION',
            fan_in: 999, fan_out: 0, callers: [], callees: [] },
        ],
      },
    },
  };
  const out = buildGraph3dData(hld, defaultFilters());
  const cold = out.nodes.find(n => n.id === 'm.cold');
  const hot  = out.nodes.find(n => n.id === 'm.hot');
  assert.equal(cold.val, 2);
  assert.equal(hot.val, 12);
});

test('caller/callee pair emits one CALLS link (deduped)', () => {
  const hld = {
    modules: {
      m: {
        qualname: 'm', file: 'm.py', symbols: [
          { qualname: 'm.a', name: 'a', kind: 'FUNCTION',
            fan_in: 0, fan_out: 1, callers: [], callees: ['m.b'] },
          { qualname: 'm.b', name: 'b', kind: 'FUNCTION',
            fan_in: 1, fan_out: 0, callers: ['m.a'], callees: [] },
        ],
      },
    },
  };
  const out = buildGraph3dData(hld, defaultFilters());
  // Even though both sides reference the edge, only one link should be emitted.
  const callLinks = out.links.filter(l => l.kind === 'CALLS');
  assert.equal(callLinks.length, 1);
  assert.equal(callLinks[0].source, 'm.a');
  assert.equal(callLinks[0].target, 'm.b');
});

test('CALLS edge filter excludes call links', () => {
  const hld = {
    modules: {
      m: {
        qualname: 'm', file: 'm.py', symbols: [
          { qualname: 'm.a', name: 'a', kind: 'FUNCTION', fan_in: 0, fan_out: 1,
            callers: [], callees: ['m.b'] },
          { qualname: 'm.b', name: 'b', kind: 'FUNCTION', fan_in: 1, fan_out: 0,
            callers: ['m.a'], callees: [] },
        ],
      },
    },
  };
  const out = buildGraph3dData(hld, defaultFilters({ edgeKinds: new Set() }));
  assert.equal(out.links.length, 0);
});

test('kind filter excludes CLASS nodes', () => {
  const hld = {
    modules: {
      m: {
        qualname: 'm', file: 'm.py', symbols: [
          { qualname: 'm.K', name: 'K', kind: 'CLASS', fan_in: 0, fan_out: 0,
            callers: [], callees: [] },
          { qualname: 'm.f', name: 'f', kind: 'FUNCTION', fan_in: 0, fan_out: 0,
            callers: [], callees: [] },
        ],
      },
    },
  };
  const out = buildGraph3dData(hld, defaultFilters({
    kinds: new Set(['FUNCTION', 'METHOD', 'MODULE']),
  }));
  assert.equal(out.nodes.length, 1);
  assert.equal(out.nodes[0].id, 'm.f');
});

test('links to filtered-out nodes are dropped', () => {
  const hld = {
    modules: {
      m: {
        qualname: 'm', file: 'm.py', symbols: [
          { qualname: 'm.K', name: 'K', kind: 'CLASS', fan_in: 0, fan_out: 1,
            callers: [], callees: ['m.f'] },
          { qualname: 'm.f', name: 'f', kind: 'FUNCTION', fan_in: 1, fan_out: 0,
            callers: ['m.K'], callees: [] },
        ],
      },
    },
  };
  const out = buildGraph3dData(hld, defaultFilters({
    kinds: new Set(['FUNCTION']),
  }));
  // CLASS node excluded, so the link to it must be dropped.
  assert.equal(out.links.length, 0);
});

test('kindColor returns documented colors per kind', () => {
  assert.equal(kindColor('FUNCTION'), '#34d399');
  assert.equal(kindColor('CLASS'), '#a78bfa');
  assert.equal(kindColor('METHOD'), '#22d3ee');
  assert.equal(kindColor('MODULE'), '#818cf8');
  // Unknown kinds get a neutral fallback (truthy string).
  assert.ok(typeof kindColor('UNKNOWN') === 'string');
});

test('edgeColor varies by edge kind', () => {
  const a = edgeColor('CALLS');
  const b = edgeColor('IMPORTS');
  const c = edgeColor('INHERITS');
  assert.notEqual(a, b);
  assert.notEqual(b, c);
});
