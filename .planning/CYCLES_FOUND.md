# Cycles in codegraph's self-graph (v0.1.0)

After resolving node-id hashes to qualnames, `codegraph analyze` reports **2 call cycles** in the codegraph repo itself. Both are described below, including whether they are real cycles or resolver artefacts.

---

## Cycle 1 — JS focus-graph navigation cycle (REAL)

**Chain:**

```
codegraph.web.static.app.hldRenderNav
 → codegraph.web.static.app.jumpToQualname
 → codegraph.web.static.app.drawFocusGraph
 → codegraph.web.static.app.hldRenderNav  (back to start)
```

**File:** `codegraph/web/static/app.js`

| Function           | Line  | Calls                |
|--------------------|-------|----------------------|
| `hldRenderNav`     | 268   | `drawFocusGraph` at line 378 |
| `drawFocusGraph`   | 456   | `jumpToQualname` at line 512 |
| `jumpToQualname`   | 427   | `hldRenderNav` at line 437   |

**Why it exists:** This is intentional UI control flow. `hldRenderNav` is the master "redraw the HLD nav panel" routine; when it draws a focused symbol it calls `drawFocusGraph`, and when the user clicks a node in the focus graph, `jumpToQualname` is invoked, which mutates `hldNav` state and re-enters `hldRenderNav` to repaint. The cycle is event-driven (user click breaks the recursion at runtime) so it is not a stack-overflow risk in practice.

**Verdict: ACCEPT.** This is a normal "redraw on user interaction" loop. The static call graph cannot tell that `jumpToQualname → hldRenderNav` only fires from a click handler. A future refactor could route the click through an event bus to break the static cycle, but it carries no runtime risk.

**Follow-up (v0.1.1+):** Consider extracting a small `nav-controller.js` module so the redraw entry point lives outside the focus-graph render path. Tracked informally — not a v0.1.0 blocker.

---

## Cycle 2 — MCP server `_serve ↔ run` (RESOLVER FALSE POSITIVE)

**Chain:**

```
codegraph.mcp_server.server._serve
 → codegraph.mcp_server.server.run
 → codegraph.mcp_server.server._serve  (back to start)
```

**File:** `codegraph/mcp_server/server.py`

| Function | Line | Actual call            |
|----------|------|------------------------|
| `_serve` | 560  | `await server.run(...)` at line 572 — `server` is an `mcp.server.Server` instance, **not** the local `run` function |
| `run`    | 579  | `asyncio.run(_serve(...))` at line 581 — real call |

**Why it exists:** This is a name-collision artefact in the resolver. The MCP `Server` class has an instance method `.run(...)` which `_serve` invokes. The current resolver collapses the bare attribute name `run` to the same-module qualname `codegraph.mcp_server.server.run`, producing a phantom edge. There is no real recursion at runtime — `_serve` awaits the MCP `Server.run` coroutine, not its own caller.

**Verdict: ACCEPT (with note).** The cycle is not a code defect; it is a known limitation of the static method-receiver resolver. Renaming the local `run` function to e.g. `main` would silence the false positive but is unnecessary. Agent F2's resolver work (`fix/resolver-r2`) may already eliminate this once it's merged — re-run `codegraph analyze` after F2 lands to confirm.

**Follow-up (v0.1.1+):** If F2 doesn't already fix this, add a heuristic: when the call site is `<local_var>.<name>(...)` and `<local_var>` is bound to a non-local class instance (e.g. `server = _build_server(...)`), do not collapse `<name>` to a same-module qualname. Tracked as a v0.1.1 resolver task.

---

## Summary

| # | Cycle                                     | Real? | Action     |
|---|-------------------------------------------|-------|------------|
| 1 | `hldRenderNav → jumpToQualname → drawFocusGraph` | Yes   | Accept; refactor candidate for v0.1.1 |
| 2 | `_serve ↔ run`                            | No    | Resolver artefact; revisit after F2 merge |

Neither cycle blocks v0.1.0 release.
