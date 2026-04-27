# Architecture: 3D Graph View

## 1. View-Registration Pattern (existing convention)

### VIEWS array — `app.js:20-32`

Every view is declared as an entry in the `VIEWS` array at the top of `app.js`. Each entry has:
- `section` (string only): renders a section header in the sidebar, no click handler
- `id` (string): route key, matches a key in `VIEW_RENDERERS`
- `label` (string): display name
- `icon` (string): Lucide icon name

### Sidebar build — `app.js:91-108`

`buildNav()` iterates `VIEWS`, creates `.nav-item` divs with `item.onclick = () => activate(v.id)`.

### Activation — `app.js:110-121`

`activate(id)` sets `state.view`, toggles `.active` on nav items, updates `#page-title` and `#crumb`, calls `render(id)`, and pushes `#<id>` to the URL hash.

### Renderer dispatch — `app.js:135-153`

`render(id)` clears `#view-host`, looks up `VIEW_RENDERERS[id]`, calls it with `host`. If not found, shows "Unknown view".

`VIEW_RENDERERS` is a plain object literal at `app.js:144-153`:
```js
const VIEW_RENDERERS = {
  overview: renderOverview,
  hld: renderHld,
  ...
};
```

### Data availability — `app.js:846-856`

All data is fetched once in `load()` from `/api/data.json` and stored in `state.data`. Every renderer reads from `state.data` synchronously. The 3D view must follow the same pattern.

### Conventions to match

- Renderer function named `render<PascalCase>` (e.g. `renderGraph3d`)
- Wrap content in `<div class="p-8 max-w-7xl mx-auto">` with a `.help-card` at top
- Use `showTip` / `hideTip` for tooltips, `toast()` for notifications
- Call `lucide.createIcons()` after inserting icon markup
- No async data fetch inside the renderer; data is already in `state.data`

---

## 2. Integration Approach: UMD CDN (Option A)

Chosen: `https://unpkg.com/3d-force-graph` UMD bundle via `<script>` tag in `index.html`.

Reasoning:
- The project has no build step and deliberately avoids one. `index.html` already loads d3, mermaid, and lucide from CDN using plain `<script>` tags (`index.html:37-40`).
- The 3d-force-graph UMD build exposes `ForceGraph3D` on `window`, matching the existing pattern of accessing `d3`, `mermaid`, `lucide` as globals.
- Self-hosting adds a maintenance burden with no benefit at this scale. The pyvis explorer pages (architecture.html, callgraph.html) are already external-link views, confirming the project is not averse to CDN dependencies.
- The library is ~750 KB gzipped. Loaded lazily (only when the view is activated), acceptable.

CDN tag to add to `index.html` immediately before `</head>`:
```html
<script src="https://unpkg.com/3d-force-graph@1/dist/3d-force-graph.min.js"></script>
```

Load it lazily: the script tag should carry `defer` so it does not block initial parse, or load it dynamically inside `renderGraph3d` if not yet present (see section 7 for the fallback path, where dynamic injection is the natural hook).

---

## 3. Data Shape

### What `/api/data.json` contains

`build_dashboard_payload` in `dashboard.py:90-155` does NOT include a raw node/edge list. It includes derived structures: `metrics`, `hotspots`, `matrix`, `sankey`, `treemap`, `flows`, `files`, `hld`.

The `hld.modules` map (`dashboard.py:148`) is the richest per-symbol structure available in the current payload. Each module entry contains `symbols[]` with `qualname`, `kind`, `fan_in`, `fan_out`, `line`, `callers[]`, `callees[]`.

However the raw graph nodes and edges are not in the payload. Two options:

**Option A (preferred, zero server change):** Synthesise force-graph data from `state.data.hld.modules`. Iterate all modules, iterate their `symbols`, emit one node per symbol. Emit one edge per caller/callee pair. This gives FUNCTION/METHOD/CLASS nodes and CALLS edges derived from callers/callees.

**Option B:** Add a new `/api/graph3d.json` endpoint returning the raw graph in force-graph format. This is cleaner for future use but requires a server change (new route in `server.py` + a new `build_graph3d_payload` function).

Recommendation: Start with Option A for day-1 speed; document Option B as a follow-up. The synthesised data from HLD modules is sufficient for a visual demo.

### Transform function (pure JS, lives in `graph3d.js`)

```js
// Input: state.data.hld
// Output: { nodes: [...], links: [...] }
function buildGraph3dData(hld, filters) {
  // filters: { kinds: Set, edgeKinds: Set, maxDepth }
  const nodeMap = new Map();
  const links = [];

  for (const [modQn, mod] of Object.entries(hld.modules || {})) {
    for (const sym of (mod.symbols || [])) {
      if (!filters.kinds.has(sym.kind)) continue;
      nodeMap.set(sym.qualname, {
        id: sym.qualname,
        name: sym.name,
        kind: sym.kind,
        file: mod.file,
        language: mod.language || '',
        fan_in: sym.fan_in,
        fan_out: sym.fan_out,
        layer: mod.layer,
      });
    }
  }

  // Edges from callers/callees (edge kind = CALLS)
  if (filters.edgeKinds.has('CALLS')) {
    for (const sym of nodeMap.values()) {
      // callers and callees come from the hld modules symbols
    }
  }

  // Size by fan_in (min 2, max 12)
  for (const n of nodeMap.values()) {
    n.val = Math.max(2, Math.min(12, 2 + n.fan_in));
  }

  return { nodes: [...nodeMap.values()], links };
}
```

Node coloring by kind:
- `CLASS` → `var(--accent-violet)` (#a78bfa)
- `METHOD` → `var(--accent-cyan)` (#22d3ee)
- `FUNCTION` → `var(--accent-emerald)` (#34d399)
- `MODULE` → `var(--brand)` (#818cf8)

Edge color by kind:
- `CALLS` → `rgba(129,140,248,0.5)` (brand)
- `IMPORTS` → `rgba(34,211,238,0.4)` (cyan)
- `INHERITS` / `IMPLEMENTS` → `rgba(167,139,250,0.5)` (violet)

Node size: `val = max(2, min(12, 2 + fan_in))` — hottest nodes appear largest.

---

## 4. UX Details

### Sidebar entry

Add to `VIEWS` in `app.js` after the existing `Diagrams` section entries (after `treemap`), before `Browse`:

```js
{ id: 'graph3d', label: '3D Graph', icon: 'atom' },
```

This places it at the bottom of `Diagrams` — appropriate because it is a diagram, not a browse tool.

### Theme parity

`graph3d.js` reads theme at render time:
```js
const isLight = document.documentElement.classList.contains('theme-light');
const bgColor = isLight ? '#f4f6fb' : '#05070d';
```

On theme toggle, `app.js:863-868` calls `render(state.view)` after re-init. `renderGraph3d` must destroy and recreate the ForceGraph3D instance to pick up new colors. Store the instance on a module-level variable; call `.instance._destructor()` (the lib's cleanup method) before recreation.

### Tooltip

Re-use `showTip` / `hideTip` (defined at `app.js:36-46`). The 3d-force-graph `onNodeHover` callback receives the node object and a DOM event-like position. Map to `showTip`:

```js
graph.onNodeHover((node, prevNode) => {
  if (!node) { hideTip(); return; }
  const { clientX, clientY } = graph.renderer().domElement
    .getBoundingClientRect();
  showTip(
    `<b>${esc(node.name)}</b><br>${node.kind} · ${esc(node.file)}<br>` +
    `in: ${node.fan_in} · out: ${node.fan_out}`,
    clientX / 2, clientY / 2  // approximate; use pointer event coords instead
  );
});
```

The library fires `onNodeHover` with the mouse event as second arg in newer versions; use that for exact coords.

### Node click — focus + details panel

`graph.onNodeClick(node => { ... })` should:
1. Set `state.graph3dFocusNode = node.id`
2. Re-render the details panel below the canvas (a `<div id="g3d-detail">`)
3. Zoom the camera to center on the node using `graph.centerAt(node.x, node.y, node.z, 800)` + `graph.zoom(4, 800)`

The details panel reuses the same HTML structure as `symbolDetailHtml` in `app.js:382-420`. Extract that function into a shared utility or duplicate minimally in `graph3d.js`.

### Filter control bar

A `<div class="g3d-controls">` strip above the canvas:

```
[ FUNCTION ] [ CLASS ] [ METHOD ] [ MODULE ]   |   [ CALLS ] [ IMPORTS ] [ INHERITS ]   |   Depth [slider 1-5]
```

Controls are toggle buttons (`.g3d-filter-btn`, `.active` class toggles). On change, call `rebuildGraph3d()` which re-runs the transform and calls `graph.graphData(newData)` for live update (no full destroy/recreate).

CSS for the control bar goes in `app.css` as `.g3d-controls`, `.g3d-filter-btn`.

### Performance threshold

At 1,577 nodes the lib handles comfortably in WebGL. Document threshold logic in code comments:
- `< 2,000 nodes`: labels on, full physics
- `2,000–5,000 nodes`: labels off by default (toggle button to enable), reduce `d3AlphaDecay` for faster settle
- `> 5,000 nodes`: disable labels, reduce link opacity, show warning toast

Implement as:
```js
const LABEL_THRESHOLD = 2000;
const DETAIL_THRESHOLD = 5000;
```

---

## 5. Demo Loop Mode (`?demo=1`)

Activated when `new URLSearchParams(location.search).get('demo') === '1'`.

### Sequence (10-second loop, repeating)

| Time | Action |
|------|--------|
| 0–2s | Slow auto-rotate (azimuth +0.3 deg/frame) |
| 2–4s | Find top hotspot node (highest `fan_in`). Camera zoom to it over 1.5s. |
| 4–6s | Hold on hotspot; show tooltip with its details. |
| 6–8s | Zoom back out to full graph over 1.5s. |
| 8–10s | Resume slow rotation; fade tooltip. |

Implementation (`DemoController` class in `graph3d.js`):
- `requestAnimationFrame` loop that increments an azimuth angle when in rotation phase
- Uses `graph.cameraPosition({ x, y, z }, { x, y, z }, ms)` for smooth transitions
- `clearInterval` / `cancelAnimationFrame` on `destroy()`

Auto-rotate: `graph.controls().autoRotate = true; graph.controls().autoRotateSpeed = 0.4` (three.js OrbitControls). During zoom-to-hotspot phases temporarily set `autoRotate = false`.

To activate demo mode the URL must include `?demo=1`. Add a "Demo" button in the control bar that appends the param and reloads:
```js
location.href = location.pathname + '?demo=1#graph3d';
```

---

## 6. File-Level Plan

### Files to Create

| File | Purpose | Priority |
|------|---------|----------|
| `codegraph/web/static/views/graph3d.js` | All 3D view logic: transform, render, demo controller | P0 |
| `codegraph/web/static/views/graph3d.css` | Styles: control bar, fallback message, WebGL unavailable banner | P0 |

### Files to Modify

| File | Changes | Priority |
|------|---------|----------|
| `codegraph/web/static/index.html` | Add `3d-force-graph` CDN script tag; add `<script src="/static/views/graph3d.js">` before `</body>` | P0 |
| `codegraph/web/static/app.js` | Three additions only: entry in `VIEWS` array (line 26-31 region), entry in `VIEW_RENDERERS` (line 144-153), add `<link>` for graph3d.css or inline in index.html | P0 |
| `codegraph/web/static/app.css` | `.g3d-controls`, `.g3d-filter-btn`, `.g3d-canvas-wrap`, `.g3d-fallback` | P0 |

### Why a separate module file?

`app.js` is already at 895 lines — close to the 800-line soft limit in the coding style rules. Extracting the 3D view into `views/graph3d.js` keeps `app.js` growth to under 10 lines (VIEWS entry + VIEW_RENDERERS entry + a `<script>` tag). It also establishes a file-per-view convention that makes the documented `app.js` split work easier later.

The module is loaded as a classic script (not `type="module"`) to avoid CORS restrictions when served from the stdlib HTTP server and to keep parity with how `app.js` itself is loaded. It reads `state`, `showTip`, `hideTip`, `toast`, `esc` as globals (they are already global in `app.js`).

The simpler alternative — inline in `app.js` — is rejected because it would push `app.js` well past 1,100 lines and make the future split harder.

### Server changes

None required for day-1 (using HLD data). If Option B (raw graph endpoint) is pursued later, add a route to `server.py:94-126` and a new payload builder.

---

## 7. Failure Modes

### CDN failure (3d-force-graph script fails to load)

In `renderGraph3d`, before calling `new ForceGraph3D()`, check:
```js
if (typeof ForceGraph3D === 'undefined') {
  host.innerHTML = fallbackHtml('3D Graph library failed to load.');
  toast('3D graph unavailable — falling back to focus graph.', 'error');
  // Optionally activate the HLD view instead:
  // activate('hld');
  return;
}
```

Show a `.g3d-fallback` div that includes a "View 2D focus graph" link that calls `activate('hld')`.

### WebGL unsupported

After creating the `ForceGraph3D` instance, the underlying Three.js renderer will fail gracefully (or throw) if WebGL is unavailable. Wrap in try/catch:
```js
try {
  const graph = ForceGraph3D()(container);
} catch (e) {
  host.innerHTML = fallbackHtml('WebGL is not supported in this browser.');
  return;
}
```

Additionally check before construction:
```js
const canvas = document.createElement('canvas');
const hasWebGL = !!(canvas.getContext('webgl') || canvas.getContext('experimental-webgl'));
if (!hasWebGL) { /* show fallback */ return; }
```

### Large graph lockup

If the node count exceeds `DETAIL_THRESHOLD` (5,000), show a `toast` warning and disable node labels before starting physics, to prevent UI freeze.

---

## 8. Test Plan

### Snapshot test of the JSON transform (pure JS, Node.js)

File: `tests/test_graph3d_transform.js` (run with `node --test` or Jest if added later)

The `buildGraph3dData` function is pure and has no DOM dependency. Extract it to the top of `graph3d.js` or into a standalone `views/graph3d_transform.js` with a `module.exports` guard:
```js
if (typeof module !== 'undefined') module.exports = { buildGraph3dData };
```

Test cases:
1. Empty HLD modules → `{ nodes: [], links: [] }`
2. One module, one FUNCTION symbol → one node, correct `val` from `fan_in`
3. Two symbols with caller/callee relationship → one link emitted
4. Filter: kind filter excludes CLASS → CLASS nodes absent from output
5. Node color mapping: FUNCTION → emerald, CLASS → violet, METHOD → cyan

### Playwright visual smoke test

File: `tests/test_graph3d_smoke.spec.js`

```js
test('3D graph view renders a WebGL canvas', async ({ page }) => {
  await page.goto('http://localhost:8765/#graph3d');
  await page.waitForSelector('#view-host canvas', { timeout: 10000 });
  expect(await page.locator('#view-host canvas').count()).toBeGreaterThan(0);
});

test('demo mode activates without JS errors', async ({ page }) => {
  const errors = [];
  page.on('pageerror', e => errors.push(e.message));
  await page.goto('http://localhost:8765/?demo=1#graph3d');
  await page.waitForTimeout(3000);
  expect(errors.filter(e => !e.includes('ResizeObserver'))).toHaveLength(0);
});
```

---

## 9. Time Estimate

| Task | Estimate |
|------|----------|
| Add CDN tag + VIEWS/VIEW_RENDERERS wiring in `app.js` + `index.html` | 15 min |
| `buildGraph3dData` transform + unit tests | 1.5 h |
| `graph3d.js` core render (init, nodes, links, tooltip, click-to-focus) | 2 h |
| Filter control bar (kind toggles, edge toggles, depth slider) | 1 h |
| Theme parity + CSS (`graph3d.css` + `app.css` additions) | 45 min |
| Demo loop controller | 1 h |
| Failure modes (CDN fallback, WebGL check) | 30 min |
| Playwright smoke tests | 45 min |
| Manual polish + screen recording for LinkedIn | 1 h |
| **Total** | **~8.5 h (1 day)** |

---

## Design Decisions

- CDN UMD over self-hosting: preserves the no-build philosophy; all existing CDN deps are external too.
- Derive graph data from `state.data.hld.modules` (already in payload) over a new endpoint: zero server change, ships faster, can be upgraded later.
- Separate `views/graph3d.js` over inline in `app.js`: stays under file-size limits, establishes view-module convention, keeps `app.js` diff small and reviewable.
- Classic script (not ES module) for `graph3d.js`: avoids CORS issues with the stdlib HTTP server's `/static/` path handling and matches how `app.js` is loaded (`index.html:93`).
- `?demo=1` URL flag over an in-app toggle: makes it trivial to share a "demo URL" and keeps demo state entirely out of the normal UI.
