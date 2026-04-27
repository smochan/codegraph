# Research: Build step / always-on labels for 3D Graph view

## Recommendation (1 sentence)

Adopt **Option 2-bis** — keep the UMD `<script src=".../3d-force-graph">` we already have, and add a tiny `<script type="module">` that does `import SpriteText from "https://esm.sh/three-spritetext"` for node + edge labels via `nodeThreeObject` / `linkThreeObject` — this is exactly what vasturiano's own `text-nodes` and `text-links` examples do, requires zero build step, and zero `window.THREE`.

## Why this beats the others

The official examples ship the UMD `3d-force-graph` and load `three-spritetext` from `esm.sh` in a sibling `<script type="module">`. `three-spritetext`'s UMD checks `window.THREE` first but its **esm.sh build** pulls its own `three` ESM and returns a class that extends `THREE.Sprite`. Crucially, `nodeThreeObject` returns an `Object3D` to the library — the library calls `.add()` on the scene; it does not introspect the prototype chain of `THREE` constructors, so a Sprite produced by a different THREE bundle still renders fine. This is verified by vasturiano shipping it as the canonical pattern.

## Comparison table

| # | Option | Friction | Browsers | Per-frame cost | Maintenance | Packaging |
|---|---|---|---|---|---|---|
| 1 | Full importmap (THREE + 3d-force-graph + spritetext via esm.sh, no UMD) | Medium — pin 3 versions | Modern only (no Safari < 16.4 import-maps polyfill needed) | Same | Have to track 3 SemVers | None |
| **2-bis** | **UMD 3d-force-graph + ESM `three-spritetext` from esm.sh** (chosen) | **Lowest** — 1 new line | All ES-module-capable (Chrome 61+, FF 60+, Safari 11+) | Same as Sprite already costs | One pin (`three-spritetext`) | None |
| 2 | UMD `three-spritetext.min.js` script | Lowest in theory but **broken** — UMD path expects `window.THREE` to exist (verified in source: `t.THREE`) which 3d-force-graph does not expose | n/a | n/a | n/a | n/a |
| 3 | Vite/esbuild bundle shipped under `web/static/dist/` | High — npm in Python repo, build step in `pyproject` (`hatch_build` hook), wheel-include glob | All | Same | Lock-step releases, CI must run `npm ci && npm run build` before `python -m build` | wheel size grows ~250 KB |
| 4 | Reach into `instance.scene().add(...)` with library-internal THREE | Medium — undocumented; 3d-force-graph never re-exports THREE | All | Custom per-tick projection needed | Brittle; breaks on minor lib bumps | None |
| 5 | DOM-overlay HTML labels positioned via `onEngineTick` + camera projection | Medium-high — write projection math, manage 50–500 absolutely-positioned divs, throttle | All | **High**: re-layout per tick, jank at >150 nodes | Own all the code | None |

## Concrete implementation spec (Option 2-bis)

### Files to modify

- `codegraph/web/static/index.html`
- `codegraph/web/static/views/graph3d.js`

### Files to add

- `codegraph/web/static/views/graph3d_labels.js` — ES module, exports `attachSpriteLabels(instance, { ESC })`. Pure module wraps `nodeThreeObject` / `linkThreeObject` config.

### Versions to pin (verified URLs)

- `https://unpkg.com/3d-force-graph@1.73/dist/3d-force-graph.min.js` (current `@1` resolves to 1.73.x — pin to a fixed minor)
- `https://esm.sh/three-spritetext@1.10.0` (matches the UMD inspected in research)

### `index.html` changes

```html
<!-- existing, keep -->
<script src="https://unpkg.com/3d-force-graph@1.73/dist/3d-force-graph.min.js"
        data-cg-3dfg></script>

<!-- NEW: an ES-module shim that exposes SpriteText globally for graph3d.js -->
<script type="module">
  import SpriteText from "https://esm.sh/three-spritetext@1.10.0";
  window.CG_SpriteText = SpriteText;
  window.dispatchEvent(new Event('cg-spritetext-ready'));
</script>
```

### `graph3d.js` changes

Replace the `loadLibrary()` promise with one that also waits for `window.CG_SpriteText`. Replace `makeLabelSprite` / `makeEdgeLabelSprite` (currently broken because `window.THREE` undefined) with `new window.CG_SpriteText(text)` and tune `.color`, `.textHeight`, `.backgroundColor`, `.padding`, `.borderRadius`. Wire via `instance.nodeThreeObjectExtend(true).nodeThreeObject(node => …)` for nodes and `linkThreeObjectExtend(true).linkThreeObject(link => link.argLabel ? new SpriteText(link.argLabel) : null).linkPositionUpdate((s,{start,end}) => …)` for edges (mirrors official `text-links` example).

Keep `nodeLabel` / `linkLabel` HTML hover for richer signature — sprite is a **complement**, not a replacement.

### Backwards compat

If browser is pre-2018 / no ESM: the `<script type="module">` is silently ignored, `window.CG_SpriteText` is `undefined`, and `graph3d.js` falls back to current HTML-hover-only behavior (already working). No new failure path.

### Rollback plan

Single commit revert. No build artifact, no migration. Set a `?nosprite=1` URL flag during shake-out that forces the fallback.

### Effort estimate

**1.5–2 hours**: 30 min to wire shim + edit `graph3d.js` (the helpers already exist), 30 min to tune textHeight/padding so labels look good at default zoom, 30 min to add Playwright test.

## Test to add

`tests/web/test_graph3d_labels.spec.ts` (Playwright, plus a Python test runner shim already used by `tests/web/`):

```ts
test('node and edge labels are visible sprites', async ({ page }) => {
  await page.goto('/?demo=1');
  await page.waitForFunction(() => !!window.CG_SpriteText);
  // wait for first focused render
  await page.waitForSelector('#g3d-canvas canvas', { state: 'visible' });
  // engine tick: pull scene children count, expect > nodeCount (each node + sprite)
  const counts = await page.evaluate(() => {
    const inst = window.__cgGraph3dInstance; // expose for tests
    const scene = inst.scene();
    const sprites = scene.children.filter(o => o.type === 'Sprite'
      || (o.children || []).some(c => c.type === 'Sprite'));
    return { sprites: sprites.length, nodes: inst.graphData().nodes.length };
  });
  expect(counts.sprites).toBeGreaterThanOrEqual(counts.nodes);
});
```

Bootstrap requirement: stash `instance` on `window.__cgGraph3dInstance` behind `?test=1`.

## Riskiest unknown

esm.sh transitive `three` resolution can drift if a future `three-spritetext` release widens its peer range — mitigated by pinning `three-spritetext@1.10.0` (current verified version). Secondary risk: a user behind a corporate network that blocks `esm.sh`; mitigation is the silent fallback noted above.

## Sources

- [3d-force-graph text-nodes example](https://github.com/vasturiano/3d-force-graph/blob/master/example/text-nodes/index.html)
- [3d-force-graph text-links example](https://github.com/vasturiano/3d-force-graph/blob/master/example/text-links/index.html)
- [three-spritetext UMD source](https://unpkg.com/three-spritetext/dist/three-spritetext.min.js)
- [three-spritetext on npm](https://github.com/vasturiano/three-spritetext)
