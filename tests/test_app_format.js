/* Tests for formatQn() in codegraph/web/static/app.js
 *
 * app.js is a classic browser script. Extract the `formatQn` function source
 * (along with its `esc` dependency) and evaluate them in a Node vm sandbox.
 *
 * Run with:  node --test tests/test_app_format.js
 */
'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const APP_JS = path.join(
  __dirname, '..', 'codegraph', 'web', 'static', 'app.js'
);

function loadFormatQn() {
  const source = fs.readFileSync(APP_JS, 'utf-8');
  const escMatch = source.match(/function esc\(s\)\s*\{[\s\S]*?\n\}/);
  if (!escMatch) throw new Error('esc() not found in app.js');
  const fmtMatch = source.match(/function formatQn\(qn,\s*opts\)\s*\{[\s\S]*?\n\}/);
  if (!fmtMatch) throw new Error('formatQn() not found in app.js');
  const sandbox = {};
  vm.createContext(sandbox);
  vm.runInContext(
    `${escMatch[0]}\n${fmtMatch[0]}\nthis.formatQn = formatQn;`,
    sandbox,
  );
  return sandbox.formatQn;
}

const formatQn = loadFormatQn();

test('formatQn renders single-segment as leaf', () => {
  const out = formatQn('foo', { maxParts: 3 });
  assert.match(out, /qn-key/);
  assert.match(out, />foo</);
});

test('formatQn dims parent path', () => {
  const out = formatQn('a.b.c', { maxParts: 3 });
  assert.match(out, /qn-dim/);
  assert.match(out, /a\.b\./);
  assert.match(out, />c</);
});

test('formatQn truncates long paths with ellipsis', () => {
  const out = formatQn('a.b.c.d.e', { maxParts: 2 });
  assert.match(out, /…/);
  assert.match(out, />e</);
});

test('formatQn escapes HTML in qn segments', () => {
  const out = formatQn('a.<b>', { maxParts: 3 });
  assert.match(out, /&lt;b&gt;/);
  assert.doesNotMatch(out, /<b>/);
});

test('formatQn handles null gracefully', () => {
  const out = formatQn(null, { maxParts: 3 });
  // null is coalesced to '' before splitting; one empty leaf, no head.
  assert.match(out, /qn-key/);
  assert.doesNotMatch(out, /null/);
});

test('formatQn defaults maxParts when opts omitted', () => {
  const out = formatQn('a.b.c.d.e');
  // default maxParts = 3 -> visible head = last 2 segments
  assert.match(out, /…/);
});
