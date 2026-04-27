# Plan — codegraph 0.1.0 polish round 2 (3-agent parallel)

**Date:** 2026-04-27
**Goal:** Land the 5 UX items the user called out on the 3D view, plus refresh launch comms and lock the v0.2 plan, then ship.

---

## Why 3 agents, not 5

All 5 of the 3D UX items (external-call filtering, inline expand/collapse, color legend, picker grouping, drop fan-in/out) live in the same 3 files: `graph3d.js`, `graph3d_transform.js`, `graph3d.css`. Splitting them by item produces guaranteed merge conflicts. They go in **one** agent (P1) as sequential commits.

The other two agents do orthogonal launch prep: P2 updates README and the LinkedIn draft to match what we actually shipped, P3 turns the v0.2 wedge ("show argument-level data flow + service classification") into an executable spec.

| Agent | Branch | Files | Worktree |
|---|---|---|---|
| P1 — 3D view polish | `feat/3d-polish` | `codegraph/web/static/views/graph3d.{js,css}`, `views/graph3d_transform.js`, `tests/test_graph3d_focus.js` | `.claude/worktrees/agent-p1-3d-polish` |
| P2 — Launch comms refresh | `docs/launch-comms` | `README.md`, `.planning/draft_linkedin.md` | `.claude/worktrees/agent-p2-comms` |
| P3 — v0.2 dataflow spec | `docs/v02-spec` | `.planning/PLAN_DATAFLOW.md`, new `.planning/PLAN_V0_2_PARAMETERS.md` | `.claude/worktrees/agent-p3-v02` |

Zero file overlap between agents.

---

## P1 — 3D view polish (all 5 UX items)

### 1. External-call filtering
Currently calls into stdlib / third-party packages (`os.path.join`, `requests.get`) appear as first-class graph nodes the user can click into. They should be **terminal leaves**: visible at the boundary as labels with a distinct gray-outline style, but not traversable.

Heuristic: if a callee/caller qualname starts with `unresolved::` OR points to a node whose module is not in `state.data.hld.modules`, treat it as external. Render once at the edge, never expand it on click.

### 2. Inline expand / collapse (replace full recenter)
The current click-to-recenter discards the existing view. Replace with **expand-on-click**:

- Click a non-root, non-external node → its 1-hop neighbors fold into the existing graph
- Click an already-expanded node → its added neighbors fold back out (collapse)
- Root stays fixed; depth slider sets initial fold-out depth

Track per-node state in a `Map<qn, {expanded: bool, originAddedIds: string[]}>`.

### 3. Color legend
Small docked panel (top-right of canvas):

- Amber dot → Ancestor (caller)
- Cyan dot → Descendant (callee)
- Purple dot → Current focus
- Gray-outline dot → External / third-party
- Kind badge legend: FN, M, C, MOD

### 4. Picker grouping with search
Replace the flat top-20 list with a grouped tree:

```
Module: codegraph.web.server
  Class: DashboardState
    payload(), rebuild()
  Function: build_payload()
Module: codegraph.parsers.python
  Class: PythonExtractor
    parse_file(), _handle_class(), …
```

Search box stays at top; results filter the tree, expanding matching parents.

### 5. Drop fan-in / fan-out from detail panel
These graph-theory metrics don't belong in the data-flow story. Remove them from the per-node detail panel. Keep them on the Hotspots view (already there).

### Tests
- `tests/test_graph3d_focus.js` already has 14 tests — extend to cover:
  - `buildFocusGraph` skips external nodes from traversal (3 tests)
  - Expand/collapse logic preserves root + dedupes (3 tests)
  - Picker grouping `groupSymbols(hld)` returns correct shape (2 tests)
- Total minimum: **22+ JS tests** passing

### Acceptance
- 5 commits on `feat/3d-polish`, one per item, in order
- All `node --test` JS tests pass
- `pytest -q` still 202 pass
- ruff + mypy --strict clean
- Browser smoke (curl-only, since we don't run a browser): `curl -s http://127.0.0.1:8765/static/views/graph3d.js | grep -c "expandNode\|collapseNode"` returns ≥ 2

---

## P2 — Launch comms refresh

### Files

- `README.md` — refresh competitive positioning + numbers + the new 3D story
- `.planning/draft_linkedin.md` — same refresh, social-tuned

### Source-of-truth numbers (use these exactly)

- Dead-code findings on self-graph: **451 → 3** (3 are intentional public APIs)
- Cycles: now reported as qualnames, not hashes (3 found, 2 accepted, 1 deferred)
- Tests: **147 → 202 pass** (Python + JS)
- Resolver patterns fixed: 5 (per-name imports, relative imports, same-file ctor, nested-fn calls, decorator edges, class-annotation `self.X.Y`, fresh-instance method chain)
- Languages: Python + TypeScript/JavaScript (resist "Python-only" framing)

### LinkedIn post

Lead with the 3D focus-mode story, not the dead-code numbers:

> *"Pick a function. See exactly what calls it and what it calls. Click any node to fold its neighbors into view, click again to fold them back. External library calls stop at the boundary — your code stays in focus."*

Then the engineering one-liner ("along the way: 451→3 false-positive dead code, 5 resolver fixes, 202 tests…") as supporting evidence.

### README changes

- Update the "Status" line to 0.1.0
- Replace the old 3D screenshot description with the focus-mode story
- Add a "What it does NOT do (yet)" section listing argument-level flow + service classification as v0.2
- Pin the competitive table — codegraph's wedge isn't "another graph tool", it's "your code's flow, not a generic graph dump"

### Acceptance

- README diff is clean, no broken markdown
- LinkedIn draft is post-ready (no `[FILL IN]` placeholders)
- 1–2 commits on `docs/launch-comms`

---

## P3 — v0.2 dataflow spec refinement

### Goal
Turn the user's two deferred items into an executable v0.2 plan:

- **Item 6:** Show argument-level data flow (`foo(user_id, role) → bar(role)` shows `role` flowing)
- **Item 7:** Service / component classification (HANDLER, SERVICE, COMPONENT, REPO roles)

### Files

- Update `.planning/PLAN_DATAFLOW.md` — existing 4-phase plan (DF1–DF4). Reread it, then merge in the parameter-tracing requirement.
- Create `.planning/PLAN_V0_2_PARAMETERS.md` — new spec for parameter capture and per-call-site argument tracking.

### Required content for `PLAN_V0_2_PARAMETERS.md`

1. **Why** — the user wants to see *what data* flows, not just which functions call which. Currently CALLS edges have no payload.
2. **Data model** — extend the `Edge` schema:
   - `metadata.args: list[str]` — positional arg expressions at the call site
   - `metadata.kwargs: dict[str, str]` — keyword arg expressions
   - `metadata.params: list[{name, type}]` on FUNCTION/METHOD nodes — extracted from def signature
3. **Parser work**:
   - Python: walk `argument_list` under `call` AST node, capture identifiers / literals (strings, numbers, names — skip complex expressions)
   - TS: same for `arguments` under `call_expression`
4. **Type capture** (best-effort):
   - Python: read function-def `parameters` block — capture annotation text per param
   - TS: read formal `parameter_list` — capture type-annotation text
5. **No type inference in v0.2** — we record what the source code says, no Mypy/Pyright integration. Inference is a v0.3 problem.
6. **Visualization**:
   - 3D view: edge label shows `arg_names` joined by `,`
   - HLD payload includes `params` per node and `args` per call edge
   - MCP `dataflow_trace` returns the chain with payload at each hop
7. **Test plan** — fixtures for: positional args, keyword args, mixed, complex expressions ignored, type-annotated params captured
8. **Out of scope** — return-value tracing, mutation tracking, any flow-sensitive analysis. Those are v0.3+.
9. **Effort estimate** — 4 days for parser + edge-payload + tests; 3 days for UI; 2 days for MCP tool extension; 1 day for docs. Total ~10 days.

### Required content for updated `PLAN_DATAFLOW.md`

- Add a new phase DF0 (before DF1): "parameter capture" — depends on `PLAN_V0_2_PARAMETERS.md`
- Adjust DF1 (FastAPI ROUTE extractor) and DF2 (React FETCH_CALL extractor) to populate `args` payload
- DF3 stitcher matches by URL pattern AND now by argument shape (e.g. POST body schema)
- DF4 dashboard adds Sankey labels showing `arg_names`
- Service classification: add a "DF1.5" — detect framework patterns (FastAPI `@router.post`, Express `app.post`, NestJS `@Controller`, React function-component) and emit `metadata.role: 'HANDLER' | 'SERVICE' | 'COMPONENT' | 'REPO'` on FUNCTION/METHOD nodes. This makes item 7 fall out of the existing extractor work.

### Acceptance

- Both files end with a clear "what gets shipped, what's deferred" table
- 1 commit on `docs/v02-spec`
- No code changes

---

## Execution

```bash
git worktree add -b feat/3d-polish     .claude/worktrees/agent-p1-3d-polish main
git worktree add -b docs/launch-comms  .claude/worktrees/agent-p2-comms     main
git worktree add -b docs/v02-spec      .claude/worktrees/agent-p3-v02       main
```

Dispatch 3 agents in parallel. Merge order after all done: P1 → P2 → P3 (P1 first since it's the only code change; P2 references the final shipped state; P3 is reference docs only).

---

## After all 3 land

1. Browser smoke test 3D polish
2. Demo recording (~2 hr)
3. PyPI publish (~30 min)
4. LinkedIn post (~30 min)
5. Then: dispatch v0.2 — start with `PLAN_V0_2_PARAMETERS.md` phase 1
