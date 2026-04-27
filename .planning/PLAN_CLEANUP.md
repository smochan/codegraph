# PLAN_CLEANUP.md — Pre-LinkedIn-Post Quality Fixes

Generated: 2026-04-26  
Scope: issues that a brand-new user or evaluator will hit first.

---

## Ship-Blockers (must fix before LinkedIn post)

1. **[#1] MCP `find_symbol` returns `kind: "NodeKind.FUNCTION"`** — breaks any MCP client filtering on kind
2. **[#4] README Quickstart has "not yet published" warning inline** — embarrassing on first read

---

## Issues — Priority Order

---

### [#1] MCP `find_symbol` (and all node-kind serialisers) returns wrong kind string

**Severity:** HIGH  
**Estimated time:** 15 min  
**File:** `codegraph/mcp_server/server.py` — lines 62, 226  

**Root cause:**  
`store_networkx.to_digraph` stores node attributes via `node.model_dump()`.  
Pydantic's default `model_dump()` preserves enum instances, not their `.value` strings.  
So `attrs["kind"]` in the networkx graph is a `NodeKind` enum instance.  
`str(NodeKind.FUNCTION)` returns `"NodeKind.FUNCTION"` (Python's `Enum.__str__` behaviour)
instead of `"FUNCTION"`.  

**Confirmed by:**  
```
>>> str(NodeKind.FUNCTION)   # → 'NodeKind.FUNCTION'
>>> NodeKind.FUNCTION.value  # → 'FUNCTION'
```

**Affected lines in server.py:**
- Line 62: `node_kind = str(attrs.get("kind") or "")`
- Line 226: `"kind": str(attrs.get("kind") or ""),`
- Identical pattern in `tool_neighbors` (line 249, 281, 301) and `tool_metrics` (line 320)

**Proposed fix (two options — pick one):**

Option A — fix at storage (preferred, fixes all consumers):  
`store_networkx.py` line 16:
```diff
-    g.add_node(node.id, **node.model_dump())
+    g.add_node(node.id, **node.model_dump(mode="json"))
```
`mode="json"` makes Pydantic serialise enums to their `.value` strings.  
Same fix for line 18 (edges).

Option B — fix at read sites in `server.py`:
```diff
-    node_kind = str(attrs.get("kind") or "")
+    raw = attrs.get("kind")
+    node_kind = raw.value if hasattr(raw, "value") else str(raw or "")
```
Repeat for every `str(attrs.get("kind") or "")` call.

Option A is cleaner — one change fixes the root cause everywhere.

---

### [#4] README "not yet published" note

**Severity:** HIGH  
**Estimated time:** 5 min  
**File:** `README.md` — lines 51, 87–93  

**Root cause:** The install section and quickstart snippet both have copy left over from pre-publish.

**Lines to update:**

Line 51 (Quickstart code block):
```diff
-pip install codegraph-py           # install from PyPI (not yet published — see Install below)
+pip install codegraph-py
```

Lines 86–93 (Install section blockquote — remove entirely):
```diff
-> **Note:** `codegraph-py` is the PyPI distribution name. The CLI command is `codegraph`.
-> The package is not yet published to PyPI — to try it today, install from source:
->
-> ```bash
-> git clone https://github.com/smochan/codegraph.git
-> cd codegraph
-> pip install -e .
-> ```
+> **Note:** `codegraph-py` is the PyPI distribution name. The CLI command is `codegraph`.
```

---

### [#2] `codegraph/web/static/app.js` is 895 lines (limit: 800)

**Severity:** MEDIUM  
**Estimated time:** 45 min  
**File:** `codegraph/web/static/app.js`  

**Root cause:** All views (HLD, Flows, Matrix, Sankey, Treemap, Architecture, Files, Overview)
plus all shared utilities live in one file.  The HLD section alone (lines 210–540) is 330 lines.

**Proposed split — plain `<script>` tags, no build step:**

| New file | Lines (approx) | Contents |
|----------|---------------|---------|
| `app-shared.js` | ~60 | `state`, `VIEWS`, tooltip, toast, `esc`, `kindIcon`, `kindColor`, `shortQn`, `formatQn` |
| `app-hld.js` | ~330 | `renderHld`, `hldRenderNav`, `symbolDetailHtml`, `jumpToQualname`, `layerTitle`, `drawFocusGraph` |
| `app-charts.js` | ~240 | `renderMatrix`, `renderSankey`, `renderTreemap` |
| `app.js` | ~265 | Early-pref IIFE, sidebar, header stats, `render`, `VIEW_RENDERERS`, `renderOverview`, `renderFlows`, `renderArchitecture`, `renderFiles`, mermaid, bootstrap (`load`) |

Load order in `index.html`:
```html
<script src="/static/app-shared.js"></script>
<script src="/static/app-hld.js"></script>
<script src="/static/app-charts.js"></script>
<script src="/static/app.js"></script>   <!-- bootstrap last -->
```

Rationale for `<script>` tags over ES modules: the file already uses `'use strict'` globals
and references D3 / Mermaid via globals; switching to `import` would require adding `type="module"`
to all scripts and rewriting D3/mermaid access — significant scope creep.  Simple `<script>`
ordering is consistent with the existing no-build philosophy.

---

### [#3] Call cycles in codegraph's own graph

**Severity:** LOW  
**Estimated time:** 0 min (no action needed)  
**File:** various  

**Cycle 1** — JS view layer (false positive / legitimate):
```
hldRenderNav → jumpToQualname → hldRenderNav   (via drawFocusGraph)
```
These three functions mutually update the HLD navigation panel. The cycle is a natural UI
feedback loop, not a logic error. The extractor creates CALLS edges for every JS function
invocation including event-driven callbacks that cannot actually recurse at runtime.
**Verdict: false positive from over-aggressive edge creation. No action.**

**Cycle 2** — MCP server entry points (legitimate wrapper pattern):
```
run → _serve     (_serve is an async coroutine; run is the sync wrapper that calls asyncio.run)
```
`run` calls `asyncio.run(_serve(...))` — there is no actual recursion here; the extractor
creates a CALLS edge from `run` to `_serve` and vice-versa because `_serve` receives `server`
from `_build_server` which is called by the module-level `run`. Tracing the code confirms
these never mutually invoke each other.
**Verdict: false positive from extractor treating co-located definitions as mutual references.
No action, but consider adding a note to the cycles documentation that JS UI loops and async
wrapper pairs are common false-positive patterns.**

---

### [#5] `print()` in `codegraph/web/server.py`

**Severity:** LOW  
**Estimated time:** 10 min  
**File:** `codegraph/web/server.py` lines 153, 154, 160  

**Root cause:** These are intentional user-facing startup messages printed to the terminal
when `codegraph serve` launches. They are not debug statements.  
They could be replaced with `logging` or `rich.print` for consistency with the CLI's Rich
usage, but this is a minor style issue only.  
**Verdict: not a bug; LOW cosmetic fix if the team wants full Rich consistency.**

---

### [#6] TODOs in code

**Severity:** LOW  
**Estimated time:** 5 min  
**File:** `codegraph/cli.py` line 50  

One TODO exists: a Rich-formatted "[yellow]TODO[/yellow] \[{name}] not yet implemented"
message shown when unimplemented CLI sub-commands are called (Phase 0 skeleton stubs).
This is user-visible if a user calls a stub command.  
**Action:** audit which commands still hit this path; either implement or remove the stub
entry-points before publication.

---

### [#7] mypy --strict + ruff status

**Severity:** NONE — both pass cleanly.

```
mypy codegraph/   → Success: no issues found in 42 source files
ruff check codegraph/ → All checks passed!
```

No action needed.

---

## Summary Table

| # | Severity | File:Line | Est. Time | Ship-blocker? |
|---|----------|-----------|-----------|--------------|
| 1 | HIGH | `store_networkx.py:16-18` (root fix) | 15 min | YES |
| 4 | HIGH | `README.md:51, 87-93` | 5 min | YES |
| 2 | MEDIUM | `web/static/app.js` (895 lines) | 45 min | No |
| 5 | LOW | `web/server.py:153-160` | 10 min | No |
| 6 | LOW | `cli.py:50` | 5 min | No |
| 3 | LOW | cycles false positives | 0 min | No |
| 7 | NONE | mypy + ruff | 0 min | No |

**Total ship-blocker work: ~20 minutes.**  
**Total all issues: ~80 minutes.**
