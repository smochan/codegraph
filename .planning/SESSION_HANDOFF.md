# Session Handoff — codegraph (post-v0.3 unified trace + arg-flow)

**Last update:** 2026-04-29
**Repo:** /media/mochan/Files/projects/codegraph
**Branch where work is happening:** `main` (PR-only merges; branch protected)
**HEAD on main as of writing:** `931190c` — `merge: fix(dataflow): backfill ROUTE entry hop args from handler DF0 params`
**Public remote:** https://github.com/smochan/codegraph (public, branch-protected)

---

## TL;DR

`codegraph` is a tree-sitter → SQLite code graph + CLI + web dashboard
(3D focus view + Architecture view + Learn Mode lifecycle modal) + MCP
server, with cross-stack data-flow tracing (DF1 → DF4), per-hop
argument-flow propagation, and an optional local embeddings layer. The
0.1.0 launch work is **functionally complete** on `main`. The only items
left to ship 0.1.0 publicly are the manual ones (record demo → tag PyPI →
post LinkedIn) — see `LAUNCH_CHECKLIST.md`.

**Current numbers:**
- **537 pytest pass** + **100 Node tests** = **637 total**, all green
- **0 dead-code findings** on the self-graph (was 451 at session-zero, 15 yesterday — pragma-marked all 15 intentional public-API methods in PR #21)
- **3 cycles**, all documented and accepted
- **15 MCP tools** registered
- **0 open PRs**

**Defensible wedge:** decorator-aware dead code + role classification (HANDLER/SERVICE/COMPONENT/REPO) + DF0 argument capture + 3D focus tracer + Architecture / Learn Mode lifecycle UI + DF4 cross-stack `dataflow trace` + **per-hop arg-flow propagation** (the launch hero shot — pick a param, watch it travel through every layer with rename annotations).

---

## What landed since last handoff (2026-04-28 → 2026-04-29)

Group by sprint, with PR numbers as anchors.

### v0.3 Unified Trace + Arg-Flow Stretch (PRs #22 → #26)

The Architecture view's Learn Mode modal now renders the *real* DataFlow
chain in Phase 4 (was generic placeholder), and a clickable param picker
highlights a single starting parameter as it travels through every layer
with rename annotations.

- **PR #22** `feat(hld): per-handler dataflow field with hop chain (v0.3 unified trace)`
  Each route entry in the HLD payload now carries `dataflow.hops[]` shaped
  to the v0.3 contract. New `shape_hops_for_handler()` in
  `analysis/dataflow.py`. Small ranking fix in `_outgoing_calls` so resolved
  callees beat decorator stubs (large quality boost on the demo trace). 10
  new tests.
- **PR #23** `feat(web/architecture): wire Phase 4 to real DataFlow hops`
  Phase 4 now renders sequence / pipeline / diagram modes from the real
  payload. Empty-hops + low-confidence states render gracefully. 17 new
  Node tests.
- **PR #24** `feat(dataflow): per-hop arg_flow mapping for value propagation`
  Every hop now carries `arg_flow: {starting_key → local_name | null}`.
  Snake_case ↔ camelCase ↔ PascalCase normalise to the same key. 27 new
  tests.
- **PR #25** `feat(web/architecture): arg-flow param picker + cross-hop highlighting`
  Chip-strip picker above the diagram. Selected param highlighted at every
  hop where `arg_flow[key]` is non-null with stable colour assignment.
  Rename annotations (`(was userId)`) when the local name differs. SMIL
  `animateMotion` dot travels the existing `dge-FROM-TO` paths in diagram
  mode (no rAF). 10 new Node tests.
- **PR #26** `fix(dataflow): backfill ROUTE entry hop args from handler DF0 params`
  The trace walker can't supply args at the entry hop (no incoming CALLS
  edge), so URL-template handlers used to produce empty `arg_flow`. Now
  backfilled from the handler node's DF0 `metadata.params`. Closes the
  launch hero shot for `GET /api/users/{user_id}`.

### Pragma-based public-API exemption (PR #21)

- New `# pragma: codegraph-public-api` (and `// ...` for TS) recognised
  above functions and classes — even above decorator stacks and as
  trailing same-line comments.
- Applied to all 15 known intentional public-API methods (`EmbeddingStore`
  facade, `SQLiteGraphStore.upsert_node` / `vacuum`, `to_dict` / `as_dict`
  serializers, `_register.decorator` closure).
- **Self-graph dead-code: 15 → 0** for the first time. The product's pitch
  ("trust this analyzer on your code") is now true of its own code.

### Docs + handoff refresh (PR #20)

- README brought current — 15 MCP tools, DF1–DF4 + Architecture view.
- Created `PLAN_V0_3_UNIFIED_TRACE.md` (now marked SHIPPED).
- This handoff doc rewritten.

### Examples cleanup + CHANGELOG (PR #19)

- Added `examples/` to the dead-code / untested skip list.
- Deleted orphaned `_propagate_class_role_to_members` helper.
- CHANGELOG brought current.

---

## Current state numbers (verified 2026-04-29)

| Metric                  | Value                                  |
|-------------------------|----------------------------------------|
| Tests passing (Python)  | **537** (3 skipped HLD-on-real-graph)  |
| Tests passing (Node)    | **100**                                |
| **Tests total**         | **637**                                |
| Dead code (self-graph)  | **0** (was 15 yesterday, 451 at start) |
| Cycles (self-graph)     | **3** (all documented & accepted)      |
| MCP tools registered    | **15**                                 |
| Open PRs                | 0                                      |
| Languages parsed        | Python, TypeScript, TSX, JavaScript    |
| Self-graph nodes        | 3,320                                  |
| Self-graph edges        | 7,557                                  |
| Cross-stack edges       | 27 FETCH_CALL · 12 ROUTE · 1 READS_FROM · 1 WRITES_TO |

The 3 cycles are documented in [`CYCLES_FOUND.md`](./CYCLES_FOUND.md):
dashboard UI redraw loop, parser self-recursion via `_visit_nested_defs`,
and the MCP `_serve ↔ run` static-resolver false positive.

---

## What's left for the public 0.1.0 launch

All code is shipped. Only manual / external steps remain:

| Step | Status | Where |
|---|---|---|
| Record demo video against `examples/cross-stack-demo` | not started | `docs/DEMO_SCRIPT.md` |
| Tag `v0.1.0` (triggers `release.yml`) | held | `LAUNCH_CHECKLIST.md` |
| PyPI publish (manual `twine upload` first to lock the name) | held | `LAUNCH_CHECKLIST.md` |
| LinkedIn launch + cross-post | held | `.planning/draft_linkedin.md` |
| Update CONTRIBUTING.md with the new test counts | optional polish | n/a |

See `LAUNCH_CHECKLIST.md` (top-level, tracked) for the concrete sequenced
steps with exact commands.

---

## What's deferred (post-launch / v0.3.x → v0.4)

| Item                                                                              | Why deferred                                              | Target |
|-----------------------------------------------------------------------------------|-----------------------------------------------------------|--------|
| Mypy / Pyright type inference                                                     | Heavy lift; not blocking 0.1.x users                      | v0.3+  |
| TS R2 resolver patterns (path aliases, fresh-instance binding, decorator edges)   | Python parity ships first; TS less critical for 0.1.0     | v0.1.2 |
| Typer CLI symbols classified `HANDLER`                                            | DF1.5 only handles HTTP frameworks today                  | v0.1.x |
| Multi-param simultaneous arg-flow highlighting                                    | Single selection enough for the launch demo               | v0.4   |
| Cross-process traces (multi-repo)                                                 | Requires linking multiple `.codegraph/graph.db` files     | v0.4   |
| Async / await visualisation                                                       | DF4 walks synchronous call graph only                     | v0.4   |
| Error-path branch rendering                                                       | Lifecycle modal shows the happy path only                 | v0.4   |
| Auth middleware as a distinct phase                                               | Today auth shows up as a regular CALL                     | v0.4   |
| Real-time `EXPLAIN` query-plan annotation                                         | Outside the static-analysis remit                         | v0.4+  |
| Benchmarks (CrossCodeEval pre-flight + SWE-bench Lite)                            | Costs money; held until 0.1.0 lands publicly              | post-launch |

---

## First action for next session

1. **Read this file**, then `LAUNCH_CHECKLIST.md`. Pick the first
   unchecked item (currently: record the demo video).
2. **If you're shipping the launch:** follow the checklist sequentially —
   demo → tag → PyPI → LinkedIn.
3. **If you're starting v0.4 work:** open
   [`PLAN_V0_3_UNIFIED_TRACE.md`](./PLAN_V0_3_UNIFIED_TRACE.md) §4
   "Out of scope (defer to v0.4)" — the v0.4 wedge candidates are listed
   there. The most impactful next is multi-param simultaneous arg-flow
   (the natural extension of what's now shipped).
4. **If something else is on fire:** the dogfood CI (`pr-review.yml`) on
   any PR will catch it; check the "review" check on the PR.

---

## Plan files index

| File | Status | Purpose |
|---|---|---|
| [`MASTER_PLAN.md`](./MASTER_PLAN.md) | reference | Original roadmap, mostly historical |
| [`PLAN_3D_VIEW.md`](./PLAN_3D_VIEW.md) | shipped | 3D focus view design |
| [`PLAN_CLEANUP.md`](./PLAN_CLEANUP.md) | shipped | Pre-launch cleanup phase |
| [`PLAN_DATAFLOW.md`](./PLAN_DATAFLOW.md) | shipped | DF0–DF4 architecture spec |
| [`PLAN_DEADCODE.md`](./PLAN_DEADCODE.md) | shipped | Decorator-aware dead-code design |
| [`PLAN_LAUNCH.md`](./PLAN_LAUNCH.md) | reference | Original launch sprint |
| [`PLAN_RESOLVER.md`](./PLAN_RESOLVER.md) | shipped | R1 / R2 / R3 resolver fixes |
| [`PLAN_V0_1_0_POLISH.md`](./PLAN_V0_1_0_POLISH.md) | shipped | First polish round |
| [`PLAN_V0_1_0_POLISH_2.md`](./PLAN_V0_1_0_POLISH_2.md) | shipped | Second polish round |
| [`PLAN_V0_2_PARAMETERS.md`](./PLAN_V0_2_PARAMETERS.md) | shipped | DF0 spec |
| [`PLAN_V0_3_UNIFIED_TRACE.md`](./PLAN_V0_3_UNIFIED_TRACE.md) | **SHIPPED 2026-04-29** | Unified trace + arg-flow |
| [`CYCLES_FOUND.md`](./CYCLES_FOUND.md) | reference | Documented self-graph cycles |
| [`RESEARCH_*.md`](.) | reference | Research outputs (attribution, benchmarks, build-step, docs audit) |
| [`draft_linkedin.md`](./draft_linkedin.md) | ready-to-post | Launch comms |

Most planning is now historical. The two files that drive ongoing work are
this handoff and the top-level `LAUNCH_CHECKLIST.md`.
