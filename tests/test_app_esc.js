/* Tests for esc() in codegraph/web/static/app.js
 *
 * app.js is a classic browser script with no module.exports guard, so we
 * extract the `esc` function source by regex and evaluate it in a Node vm
 * sandbox. This isolates the helper without touching production code.
 *
 * Run with:  node --test tests/test_app_esc.js
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

function loadEsc() {
  const source = fs.readFileSync(APP_JS, 'utf-8');
  // Find the `function esc(s) { ... }` block. Body spans 3 lines in the
  // current file; capture greedily up to the next blank line.
  const match = source.match(/function esc\(s\)\s*\{[\s\S]*?\n\}/);
  if (!match) throw new Error('esc() not found in app.js');
  const sandbox = {};
  vm.createContext(sandbox);
  vm.runInContext(`${match[0]}\nthis.esc = esc;`, sandbox);
  return sandbox.esc;
}

const esc = loadEsc();

test('escapes ampersand', () => {
  assert.equal(esc('a & b'), 'a &amp; b');
});

test('escapes angle brackets', () => {
  assert.equal(esc('<script>'), '&lt;script&gt;');
});

test('escapes double quotes', () => {
  assert.equal(esc('say "hi"'), 'say &quot;hi&quot;');
});

test('escapes single quotes', () => {
  assert.equal(esc("it's"), 'it&#39;s');
});

test('null becomes empty string', () => {
  assert.equal(esc(null), '');
});

test('undefined becomes empty string', () => {
  assert.equal(esc(undefined), '');
});

test('plain string passes through unchanged', () => {
  assert.equal(esc('hello world'), 'hello world');
});

test('numbers are stringified', () => {
  assert.equal(esc(42), '42');
});

test('escapes mixed special characters', () => {
  assert.equal(
    esc(`<a href="x">&'</a>`),
    '&lt;a href=&quot;x&quot;&gt;&amp;&#39;&lt;/a&gt;'
  );
});

test('empty string returns empty string', () => {
  assert.equal(esc(''), '');
});
