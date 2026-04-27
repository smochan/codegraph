# Session Handoff — codegraph 0.1.0 (pre-public-push)

**Last update:** 2026-04-26
**Repo:** /media/mochan/Files/projects/codegraph
**Branch on which work is happening:** `main` (parallel feature branches merge in)
**Doc-refresh branch:** `docs/refresh-v010` (this handoff lives here until merged)
**HEAD on main as of writing:** `393faca` — `fix(web/3d): legend wasn't rendering; switch labels to library-native HTML hover`

---

## TL;DR for the next session

`codegraph` (tree-sitter → SQLite code graph + CLI + web dashboard + MCP server)
has had three more sprints land since the last handoff was written. The original
0.1.0 launch sprint shipped, then we ran a **3D-polish round**, then a
**v0.2 wedge round** (DF0 params/args + DF1.5 role classification + 3D consumer),
then a **legend-render quick fix**. The README + CHANGELOG + LinkedIn draft were
out of date and have been refreshed on `docs/refresh-v010`.

**Public push is held.** PyPI publish is intentionally deferred until the
launch comms (LinkedIn, Reddit, X) and the always-on sprite-text label work
(W1-A, in flight on a separate worktree) settle. Status badge and CHANGELOG
both say "in-progress / pre-release."

The space is crowded — GitNexus (28K stars), code-review-graph,
better-code-review-graph, JudiniLabs/mcp-code-graph, sdsrss/code-graph-mcp,
RepoMapper, Graphify. We are explicitly **not** a fork of any of them; see
`RESEARCH_ATTRIBUTION.md` (the recommended Prior-Art language is now in the
README). The defensible wedge is decorator-aware dead code + role
classification + DF0 argument capture + 3D focus tracer, with v0.2 cross-stack
data-flow tracing as the bigger bet.

---

## What landed (chronological, by sprint)

Use `git log --oneline | head -50` for the live list. Grouped here for narrative.

### Original 0.1.0 launch sprint (4-agent parallel) — pre-existing

- `f8bbd56` — feat(web): 3D force-directed graph view (vasturiano/3d-force-graph)
- `de8779b` — fix(resolver): per-name imports + relative imports + `self.X.Y` chain (R1)
- `efeae29` — feat(deadcode): decorator-aware entry-point detection (D1)
- `bb16f7e` — fix: serialize NodeKind/EdgeKind enums as `.value` strings in MCP responses

### Round 1 — F4/F2/F3/F1 sprint

- `a845d35` — merge: feat(cycles): qualname resolution in `analyze` and MCP
  - `5ef4a62` feat(cycles): include qualnames in MCP cycles tool response
  - `f180478` feat(cycles): resolve node-id hashes to qualnames in analyze report
  - `a48ca73` docs: document the 2 cycles found in self-graph
- `d59868e` — merge: fix(resolver): R2 patterns — ctor / nested / decorator / class-annotation / fresh-instance (10 → 3 dead)
  - `537e8bf` fix(resolver): emit CALLS edge for decorator expressions (R2-3)
  - `ea244c2` fix(resolver): bind `self.X` via class-level type annotations (R2-4)
  - `26c5a05` fix(resolver): bind method calls on fresh instance constructions (R2-5)
  - `5078834` fix(resolver): scope-relative lookup for nested calls + MCP entry points
- `a1d6087` — merge: test: cover top-10 high-fanin untested helpers (224 → 214)
  - 7 commits adding tests for `_common`, `parsers.base.node_text`, `cli` helpers,
    `mcp_server._resolve_node`, `typescript._collect_calls`,
    `web.server.DashboardState`, and `app.esc`
- `9af4f1f` — feat(web/3d): replace force-cloud with focus-mode flow tracer

### Round 2 — P1/P2/P3 sprint

- `6b2f033` — merge: feat(web/3d): polish round (5 UX items)
  - `c386477` feat(web/3d): treat stdlib/third-party calls as terminal leaves
  - `26221c5` feat(web/3d): inline expand/collapse instead of full recenter
  - `038ebbe` feat(web/3d): add dismissible color and kind legend
  - `351627e` feat(web/3d): grouped, searchable symbol picker (modules/classes/methods)
  - `a028c36` feat(web/3d): drop fan-in/fan-out from detail panel
- `cebb1ec` — merge: docs: refresh README + LinkedIn draft for 0.1.0 launch
  - `fbbb4b4` docs(readme): refresh for 0.1.0 — focus-mode story, honest scope, real numbers
  - `9f72327` docs(linkedin): post-ready 0.1.0 launch draft + pinned-comment template
- `b4e7bb6` — merge: docs(planning): fold parameter capture + service classification into v0.2 spec
  - `0d03227` docs(planning): fold parameter capture + service classification into v0.2 spec

### Round 3 — V1/V2/V3/V4/V5 v0.2-precursor sprint

- `24d18ac` — merge: feat(parser/py): DF0 — capture function signatures + per-call-site args
  - `94da0d3` feat(parser/py): capture function signatures + per-call-site args (DF0)
  - `782b3a5` test(df0/py): comprehensive fixtures + tests
- `c0cdba6` — merge: feat(parser/ts): DF0 — capture function signatures + per-call-site args/kwargs
  - `abac387` feat(parser/ts): capture function params + return-type annotations (DF0)
  - `08d0370` test(df0/ts): fixtures + tests for params, returns, and call args/kwargs
- `3f88a83` — merge: feat(analysis): role classification (HANDLER/SERVICE/COMPONENT/REPO) — DF1.5
  - `5dcb6f6` feat(analysis): role classification — DF1.5
  - `ce7ded5` test(roles): fixtures + 10 tests across py + ts
- `97aeb33` — merge: feat(hld+mcp): surface DF0/DF1.5 metadata in HLD payload + MCP tools
  - `3758169` feat(hld): surface params/returns/role + callee_args in payload (DF0/DF1.5)
  - `01343db` feat(mcp): include params/role in find_symbol/callers/callees + role filter
  - `2776c71` test: HLD payload + MCP dataflow tool responses
- `115878e` — merge: feat(web/3d): consume DF0/DF1.5 — always-visible labels, edge args, role-grouped picker, signature tooltips
  - `2dc723d` feat(web/3d): always-visible node name labels
  - `900b3cc` feat(web/3d): edge labels showing call args + kwargs (DF0)
  - `18701d5` feat(web/3d): role-grouped picker (HANDLER/SERVICE/COMPONENT/REPO) — DF1.5
  - `9d65462` feat(web/3d): signature tooltip with params + return type (DF0)
  - `ef54176` feat(web/3d): legend expanded by default + role color chips

### Quick fix

- `393faca` — fix(web/3d): legend wasn't rendering; switch labels to library-native HTML hover

### In flight (separate worktree, not yet merged)

- **W1-A always-on labels via `three-spritetext`** — replace HTML hover labels
  with sprite-text labels that float in 3D space and stay readable from any
  angle. Branch on a sibling worktree. Will land as v0.1.1 once smoke-tested.

---

## Numbers as of last `analyze` (HEAD `393faca`, fresh build)

| Metric | Value |
|---|---|
| Nodes | **2259** |
| Edges | **4963** (CALLS=3495, DEFINED_IN=814, IMPORTS=634, INHERITS=20) |
| Unresolved edges | 2746 |
| Dead-code findings on self-graph | **4** |
| Cycles | **3** (UI redraw loop, parser `_visit_nested_defs`, MCP `_serve↔run`) |
| Untested functions reported | 272 |
| Languages | python=1007, javascript=67, typescript=25, tsx=12 (plus FILE/MODULE) |
| Python tests | **270 passed + 3 skipped = 273** (`pytest -q`) |
| Node tests | **55** across `test_graph3d_focus.js`, `test_graph3d_transform.js`, `test_app_esc.js` |
| MCP tools | 10 (find_symbol, callers, callees, blast_radius, subgraph, dead_code, cycles, untested, hotspots, metrics) |
| Framework decorators recognized | 24 |

Dead-code findings (the 4):

- `codegraph.analysis.roles._propagate_class_role_to_members`
- `codegraph.graph.store_sqlite.SQLiteGraphStore.upsert_node`
- `codegraph.graph.store_sqlite.SQLiteGraphStore.vacuum`
- `codegraph.mcp_server.server._register.decorator`

---

## What's deferred and why

| Item | Defer to | Reason |
|---|---|---|
| Always-on sprite-text labels in 3D view | v0.1.1 | W1-A in flight on separate worktree; library-native HTML labels are good enough today. |
| Dashboard screenshots in README (`docs/images/`) | v0.1.1 | Need to record after sprite-text labels land for final visual. |
| TypeScript R2 resolver patterns (path aliases, fresh-instance binding, decorator-call edges) | v0.1.2 | Avoided touching `parsers/typescript.py` while DF0 work was in flight. |
| Typer CLI `HANDLER` classification | v0.1.x follow-up | DF1.5 is HTTP-framework-aware only. |
| Cross-stack data flow (DF1 routes, DF2 fetch, DF3 stitcher, DF4 trace) | v0.2 | The real wedge. ~2 weeks across 4 phases. See `PLAN_DATAFLOW.md`. |
| Type inference (Mypy / Pyright) | v0.3+ | DF0 captures text only; flowed types are a separate epic. |
| PyPI publish (`codegraph-py`) | After launch comms ready | Holding the name will happen with manual `twine upload` first; see `PLAN_LAUNCH.md`. |
| LinkedIn / Reddit / X public launch | After PyPI live + screenshots | Don't post until install path is verified end-to-end. |
| Show HN | After v0.2 wedge ships | Avoids "this is just GitNexus lite" as the top comment. |
| **Benchmark eval** | Post-public-launch | **User explicit choice to defer.** `RESEARCH_BENCHMARKS.md` lays out a CrossCodeEval pre-flight (~$50, hours, no agent loop) and SWE-bench Lite + Agentless run (~$400–900, 24–48h, 3,600 model calls across 4 arms × 3 seeds) targeting +2 to +4 absolute resolve-rate gain over the published RepoGraph result. Critical comparison cell is T3 (codegraph context vs RepoGraph context, same model, same harness) — that's the cell that proves "structurally a superset" is real. |

---

## Active plan files index — `.planning/`

| File | Purpose | Status |
|---|---|---|
| `MASTER_PLAN.md` | Two-track execution map | reference (slightly stale on what shipped post-launch) |
| `PLAN_CLEANUP.md` | F: ship-blockers | DONE (`bb16f7e`) |
| `PLAN_DEADCODE.md` | B: decorator-aware dead code | D1 DONE (`efeae29`); D2 (TS) deferred to v0.1.x |
| `PLAN_RESOLVER.md` | A: resolver fixes | R1 DONE (`de8779b`), R2 DONE (`d59868e`); TS R2 deferred to v0.1.2 |
| `PLAN_3D_VIEW.md` | C: 3D force-graph view | DONE (`f8bbd56`) + focus-mode (`9af4f1f`) + polish (`6b2f033`) + DF0/DF1.5 consumer (`115878e`) |
| `PLAN_V0_1_0_POLISH.md`, `PLAN_V0_1_0_POLISH_2.md` | round-2 + round-3 polish specs | DONE |
| `PLAN_V0_2_PARAMETERS.md` | DF0 + role classification spec | DONE through DF0 + DF1.5; DF1–DF4 still pending |
| `PLAN_LAUNCH.md` | E: PyPI + demo + LinkedIn | spec ready, awaiting manual launch |
| `PLAN_DATAFLOW.md` | D: cross-stack data-flow tracing | NOT STARTED — v0.2 wedge, 4 phases (DF1→DF4) |
| `CYCLES_FOUND.md` | the 3 cycles + verdict each | reference |
| `RESEARCH_DOCS_AUDIT.md` | the punch list this handoff is based on | DONE — fixes landed on `docs/refresh-v010` |
| `RESEARCH_ATTRIBUTION.md` | "is codegraph a fork?" verdict | DONE — Prior Art section now in README |
| `RESEARCH_BENCHMARKS.md` | benchmark eval plan (CrossCodeEval + SWE-bench Lite) | reference; deferred (see above) |
| `RESEARCH_BUILD_STEP.md` | sprite-text labels build/no-build options | reference; W1-A in flight |
| `draft_linkedin.md` | shipped LinkedIn copy | numbers refreshed for current state |
| `SESSION_HANDOFF.md` | this file | active |

---

## First action for the next session

1. Read this file end-to-end.
2. `git log --oneline | head -10` — confirm HEAD and check whether W1-A
   (sprite-text labels) and W1-B (this docs refresh) have merged.
3. Decide which lane to push next:
   - **(A)** Manual launch — record screenshots, PyPI publish, LinkedIn post
     (steps in `PLAN_LAUNCH.md` §"Manual steps left").
   - **(B)** v0.1.2 lane — TS R2 resolver patterns; CLI HANDLER classification.
   - **(C)** v0.2 wedge — start `PLAN_DATAFLOW.md` DF1 (FastAPI ROUTE +
     SQLAlchemy READS_FROM/WRITES_TO).
   - **(D)** Benchmark eval — only after public launch ships. Start with
     CrossCodeEval pre-flight per `RESEARCH_BENCHMARKS.md` §4.

Most likely default: **(A) launch comms** once W1-A sprite-text labels merge,
because the in-flight visual is what the LinkedIn loop video will actually show.
