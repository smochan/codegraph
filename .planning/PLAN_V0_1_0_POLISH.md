# Plan — codegraph 0.1.0 polish (4-agent parallel execution)

**Date:** 2026-04-27
**Goal:** Convert 0.1.0 from "look I built a tool" to "this has a story." Fix the resolver, ship the 3D focus mode, push test coverage, resolve cycles to qualnames — all in one parallel pass.

---

## Agent map at a glance

| Agent | Branch | Owned files | Worktree |
|---|---|---|---|
| F1 — 3D focus mode | `feat/3d-focus-mode` | `codegraph/web/static/views/*`, possibly `web/server.py` (one new endpoint) | `.claude/worktrees/agent-f1-3d-focus` |
| F2 — Resolver fixes | `fix/resolver-r2` | `codegraph/parsers/python.py`, `codegraph/parsers/typescript.py`, fixtures under `tests/fixtures/resolver_r2/` | `.claude/worktrees/agent-f2-resolver` |
| F3 — Test coverage push | `test/top-untested-coverage` | `tests/` only (new files) | `.claude/worktrees/agent-f3-tests` |
| F4 — Cycle qualname resolver | `feat/cycle-qualnames` | `codegraph/analysis/cycles.py`, `codegraph/analysis/report.py` | `.claude/worktrees/agent-f4-cycles` |

**Zero file overlap between agents.** F1 ↔ web/static, F2 ↔ parsers/, F3 ↔ tests/, F4 ↔ analysis/. All four can run truly in parallel without merge conflicts.

---

## F1 — 3D Focus Mode (the story)

**Why:** Current 3D is a 326-node force cloud with no narrative. User wants: *"pick a function, see what flows in and out, click to drill."*

### Scope

1. **Default state:** empty canvas + prominent search input. Help card reads *"Pick a symbol to trace its data flow."*
2. **Symbol picker:** search-as-you-type over `state.data.hld.modules[*].symbols[*].qualname`. Show top-20 matches with kind badges.
3. **Focus render:**
   - Selected node centered, larger, highlight color
   - Ancestors (callers) flow in from one side, color A (e.g. amber)
   - Descendants (callees) flow out the other side, color B (e.g. cyan)
   - Edges directed and color-coded
4. **Controls:**
   - Depth slider: 1, 2, 3, 4 hops (default 2)
   - Direction toggle: `ancestors only / descendants only / both` (default both)
5. **Click-to-recenter:** clicking any node makes it the new focus. Breadcrumb above canvas shows last 3 focuses.
6. **Reset:** clears focus back to picker state (not "show all").

### Implementation

- New transform fn in `graph3d_transform.js`: `buildFocusGraph(hld, rootQn, depth, direction)` — BFS from root over caller/callee edges in HLD payload, return same `{nodes, links}` shape with `role: 'root' | 'ancestor' | 'descendant'` on each node.
- `graph3d.js` becomes a stateful focus controller: focus state `{ rootQn, depth, direction, history: [] }` replaces `lastFilters`.
- Kept: WebGL fallback, demo URL flag (`?demo=1` autoplays a tour through 3 hand-picked focuses).
- Removed: kind/edge filter buttons (orthogonal to focus story; can return in v0.1.1 as a side-panel).

### Tests

- 8+ tests in `tests/test_graph3d_focus.js` (node --test):
  - empty root → empty graph
  - root with no callers/callees → 1 node
  - depth=2 with chain → correct hop count
  - direction filters work in isolation
  - cycle in graph doesn't infinite-loop
  - role assignment is correct
- Browser smoke test before merge.

### Acceptance

- Demo URL `http://127.0.0.1:8765/#graph3d` shows picker, not cloud
- Picking `web.server._Handler.do_GET` shows ~5–10 nodes (its actual neighborhood)
- Depth slider visibly changes the hop count
- All 147 existing tests still pass
- 8 new JS tests pass

---

## F2 — Resolver fixes (R2)

**Why:** 10 remaining "dead code" findings on self-graph are all resolver false positives. Fixing them benefits every codebase codegraph analyzes, not just ours.

### Five patterns to fix

| # | Pattern | Example | Test fixture |
|---|---|---|---|
| 1 | Same-file constructor calls | `LayerSpec(...)` in viz/hld.py:51 | `tests/fixtures/resolver_r2/same_file_ctor.py` |
| 2 | Same-file nested-function calls | `_safe_id` called inside `_emit_node` (viz/mermaid.py:69) | `tests/fixtures/resolver_r2/nested_call.py` |
| 3 | Decorator-call edges | `@_register("...")` should emit CALLS edge to `_register` | `tests/fixtures/resolver_r2/decorator_call.py` |
| 4 | `self.X.Y()` through class-level annotation | `self.state.payload()` where `state: DashboardState` is a class annotation, not in `__init__` | `tests/fixtures/resolver_r2/class_annotation.py` |
| 5 | Method calls through fresh instances | `Klass(arg).method()` chain | `tests/fixtures/resolver_r2/instance_chain.py` |

### Implementation strategy

- Each fix lives in `codegraph/parsers/python.py` (resolver section). TS parity is **deferred to v0.1.2** unless trivial.
- Each fix is a separate commit in this branch (5 commits total) so review can be staged.
- Each fix has 1+ unit test in `tests/test_resolve_r2.py`.

### Acceptance

- All 5 fixtures produce expected CALLS edges
- Self-graph rebuild: dead-code drops from 10 → ≤2 (the 2 may be `vacuum`/`upsert_node`, which are genuinely unreferenced public API — acceptable)
- All 147 + 5 new tests pass
- ruff clean, mypy --strict clean

---

## F3 — Test coverage push

**Why:** 224 untested functions is a weak narrative beat. Closing the top-fanin gaps lifts coverage and gives us real signal about regressions.

### Targets (top 10 by caller count)

1. `analysis._common._kind_str` — 21 callers (already partially tested via consumers, add direct unit tests)
2. `parsers.base.node_text` — 15 callers
3. `web/static/app.js esc` — 11 callers (JS, node --test)
4. `cli._get_data_dir` — 9 callers
5. `cli._open_graph` — 8 callers
6. `mcp_server.server._resolve_node` — 4 callers
7. `analysis._common.in_test_module` — 3 callers (extend with new path-based fallback test)
8. `parsers.typescript.TypeScriptExtractor._collect_calls` — 3 callers
9. `web.server.DashboardState._build_payload` — 2 callers
10. `web.server._Handler._send_bytes` — 3 callers (handler unit test with mock socket)

### Implementation

- New test files: `tests/test_common_helpers.py`, `tests/test_cli_helpers.py`, `tests/test_resolve_helpers.py`, `tests/test_web_handler.py`, `tests/test_app_esc.js`
- Each function: 3–5 tests (happy path, edge case, error case)
- No production code changes — pure test additions

### Acceptance

- 30+ new tests added
- `pytest -q` reports 177+ pass
- `codegraph analyze` untested-count drops from 224 → ~190
- Coverage report shows targeted helpers at 80%+

---

## F4 — Cycle qualname resolver

**Why:** Current report shows opaque hashes:
```
### Call cycles (2)
- 13664b61... → 8a8489... → 91a1802...
- 21490f0... → ff6b9f76...
```
Should show qualnames so the 2 cycles can be discussed in the demo.

### Implementation

- `codegraph/analysis/cycles.py`: existing `find_cycles` returns node IDs. Either resolve to qualnames inside the function, or update `analysis/report.py` to look up qualnames before printing.
- Same fix for MCP `cycles` tool response — return qualnames not hashes.
- Identify what the 2 actual cycles are. Document them in a comment in the file with the cycle, OR file as v0.1.1 issues with a `# noqa: cycle-known` style marker.

### Acceptance

- `codegraph analyze` cycle section shows readable qualnames
- 2 cycles identified, root-caused, documented (fix or accept-and-comment)
- 2 new tests in `tests/test_cycles_report.py`
- mypy --strict clean

---

## Execution

### Step 1 — Spawn worktrees in parallel

```bash
cd /media/mochan/Files/projects/codegraph
git worktree add -b feat/3d-focus-mode    .claude/worktrees/agent-f1-3d-focus     main
git worktree add -b fix/resolver-r2       .claude/worktrees/agent-f2-resolver     main
git worktree add -b test/top-untested-coverage .claude/worktrees/agent-f3-tests   main
git worktree add -b feat/cycle-qualnames  .claude/worktrees/agent-f4-cycles       main
```

### Step 2 — Dispatch all four agents in parallel

Single message, 4 Agent tool calls (general-purpose). Each gets:
- Working directory = its worktree
- This plan file as context
- The specific section that applies
- Acceptance criteria
- Instruction to commit + run tests + report PR-ready summary

### Step 3 — Merge order (sequential, after all agents finish)

Sequential merges to avoid surprise integration:

1. **F4 first** (smallest, lowest risk, isolated to analysis layer)
2. **F2 second** (resolver — affects what self-graph reports next)
3. **F3 third** (tests only — no behavior change, validates F2 by example)
4. **F1 last** (UI layer, depends on no other agent's output)

After each merge: run full `pytest -q` + `ruff check .` + `mypy --strict codegraph` before merging the next.

### Step 4 — Worktree cleanup

After all merges land on main:

```bash
git worktree remove -f -f .claude/worktrees/agent-f1-3d-focus
git worktree remove -f -f .claude/worktrees/agent-f2-resolver
git worktree remove -f -f .claude/worktrees/agent-f3-tests
git worktree remove -f -f .claude/worktrees/agent-f4-cycles
git branch -D feat/3d-focus-mode fix/resolver-r2 test/top-untested-coverage feat/cycle-qualnames
```

(Yesterday's worktree-pollution lesson applies: leftover worktrees produce 4× duplication in the self-graph.)

### Step 5 — Manual launch sequence

Once polish lands:

1. Browser smoke test all 4 changes
2. Record demo videos (storyboard in `PLAN_LAUNCH.md`)
3. PyPI publish (`twine upload` first, then tag push)
4. LinkedIn post (use updated metrics from final analyze)

---

## Time estimate

| Phase | Wall-clock |
|---|---|
| 4 agents in parallel | 60–90 min |
| Sequential merges + verification | 30 min |
| Demo recording | 2 hr |
| PyPI + LinkedIn | 1 hr |
| **Total to launch** | **~4–5 hours** |

vs. doing them sequentially: ~10 hours. Parallel saves a half-day.

---

## Out of scope (deferred to v0.1.1+)

- TS resolver parity for the 5 R2 patterns
- TS path aliases (`@/` style imports) — was R2 in original PLAN_RESOLVER
- TS NestJS / Next.js page-export decorator detection (was D2 in PLAN_DEADCODE)
- DataCodeConfig user-facing config UX (was D3)
- IMPORTS / INHERITS edge support in 3D focus mode
- Playwright test for 3D view
- Cross-stack data flow (frontend↔API↔DB) — that's v0.2, see `PLAN_DATAFLOW.md`

---

## First action when ready

User says "go" → spawn the 4 worktrees, dispatch the 4 agents in one message, wait for all to complete, then merge in order F4 → F2 → F3 → F1.
