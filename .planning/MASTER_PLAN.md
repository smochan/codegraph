# codegraph — Master Execution Plan

Synthesized from 6 parallel planning agents. Two tracks, four implementation waves.

---

## Two tracks

| Track | Goal | Plans | Time |
|---|---|---|---|
| **T1: Ship 0.1.0 publicly TODAY** | Clean demo, PyPI live, LinkedIn post out | F → (A.R1 ‖ B ‖ C) → E.demo → E.publish → E.post | 1 day |
| **T2: v0.2 wedge** | Cross-stack data-flow tracing — the actual moat | D (DF1→DF2→DF3→DF4) | ~2 weeks |

T1 and T2 are independent. T2 starts whenever; it does not block today's launch.

---

## Dependency graph (T1)

```
                                ┌─ A.R1 (resolver)  ─┐
F.cleanup (20 min) ─────────────┤                    ├─ E.demo ─ E.publish ─ E.post
  store_networkx.py + README    ├─ B.deadcode        │           (manual)    (manual)
                                ├─ C.3D view ────────┘
                                │
                                └─ (all parallel, ~1 day)
```

**Why F first and alone:** the `NodeKind.FUNCTION` enum-repr bug (one-line fix at `store_networkx.py:16,18`) corrupts every MCP response. Demo and publish must follow it. README "not yet published" must go before publish.

**Why A, B, C run parallel:** they touch different code regions. File-conflict matrix below.

---

## File conflict matrix (A, B, C)

| Agent | Files touched |
|---|---|
| **A.R1** | `parsers/python.py` (`_handle_import_from`), `parsers/typescript.py` (`_handle_import`), `resolve/calls.py` (`_build_import_bindings`, `_resolve_target` heuristic 1) |
| **B** | `parsers/python.py` (add `_is_entry_point`), `parsers/typescript.py` (add `_get_ts_decorators`), `analysis/dead_code.py`, `config.py` |
| **C** | `web/static/views/graph3d.js` (new), `web/static/index.html`, `web/static/app.js` (≤10 lines), `web/static/app.css` |

**Conflict:** A and B both edit `parsers/python.py` and `parsers/typescript.py` — but in different functions. Three options:

1. **Worktree isolation** (cleanest) — each agent works on a branch, manual merge after. Adds 10 min.
2. **Serialize: B → A** (B is smaller, safer) — wastes the parallelism.
3. **Single combined agent for A+B** — fewer hand-offs, slightly more context per agent.

**Recommendation:** **Option 1 (worktrees)** — uses the `EnterWorktree` tool, gives both agents clean diffs that merge with zero conflict in practice (different functions in same file).

C has zero overlap — runs fully parallel.

---

## Wave plan

### Wave 0 (now): plans written ✅
All 6 plans landed in `.planning/`. Total: 1 day of design work compressed into ~5 minutes wall-clock via parallel dispatch.

### Wave 1: Cleanup + 3D view (parallel)
- **F-impl** (no worktree, ~20 min):
  - `store_networkx.py:16,18` — change to `model_dump(mode="json")`
  - `README.md:51, 87–93` — remove "not yet published" notes
  - Run pytest, mypy, ruff
- **C-impl** (worktree, ~1 day): build 3D view per `PLAN_3D_VIEW.md`

These run concurrently because F is on main and C is on a worktree. F finishes in 20 min; C runs all day.

### Wave 2: Resolver R1 + Decorator-aware dead code (parallel, both worktrees)
Dispatched **after F lands** (so both agents pull a clean main).

- **B-impl**: implement `PLAN_DEADCODE.md` Phase D1 (Python: Typer/Click/FastAPI/pytest). Skip D2 (TS) and D3 (config) for today; add issues for v0.1.1.
- **A-impl-R1**: implement `PLAN_RESOLVER.md` Phase R1 (named imports + relative imports + `self.X.Y` chains). Skip R2 (TS path aliases) for today.

Each agent uses `EnterWorktree`. Manual merge order: B first (smaller), then A.

### Wave 3: Verification + demo
After A, B, C all merged to main:

- Re-run `codegraph build` on the codegraph repo itself.
- Verify:
  - `metrics`: unresolved-edge rate dropped from 61% → target ≤30% (R1 alone)
  - `dead_code`: CLI commands no longer flagged
  - MCP `find_symbol`: returns `"FUNCTION"` not `"NodeKind.FUNCTION"`
  - `serve` → 3D view renders, demo loop works
- **E.demo**: record 45s landscape MP4 + 5s silent square loop per `PLAN_LAUNCH.md` §2. Manual — needs OBS/screen-record. Storyboard ready.

### Wave 4: Publish + post (manual, needs your hands on the wheel)
- **E.publish** (~1 hour, manual):
  1. `python -m build` + `twine check dist/*`
  2. Manual `twine upload` first (lock the `codegraph-py` name)
  3. `gh secret set PYPI_API_TOKEN`
  4. `git push origin v0.1.0` → triggers release.yml
  5. Smoke test `pip install codegraph-py` in fresh venv
- **E.post** (~30 min, manual): post `draft_linkedin.md` to LinkedIn, pin comparison-table comment, cross-post to r/LocalLLaMA, r/ClaudeAI, r/Python, X.

---

## Subagent dispatch — Wave 2 brief (preview)

When you say go, I'll dispatch:

| Agent | Type | Worktree | Plan file | Output |
|---|---|---|---|---|
| F-impl | `general-purpose` | no (on main) | `PLAN_CLEANUP.md` ship-blockers only | commit on main |
| B-impl | `general-purpose` | yes | `PLAN_DEADCODE.md` Phase D1 | branch ready to merge |
| A-impl-R1 | `general-purpose` | yes | `PLAN_RESOLVER.md` Phase R1 | branch ready to merge |
| C-impl | `general-purpose` | yes | `PLAN_3D_VIEW.md` full | branch ready to merge |

Each agent gets:
- The plan file path (single source of truth — agents read it, don't re-derive)
- A "you may NOT modify these files" list (cross-conflict guard)
- TDD requirement (tests first, per the global rules)
- Verification commands (`pytest`, `mypy --strict`, `ruff check`)
- Strict scope: "if a task in the plan is marked R2/D2/D3 — skip it, today is R1/D1 only"

---

## Track 2: v0.2 dataflow wedge (parallel, separate week)

`PLAN_DATAFLOW.md` is the build spec. Four sub-phases, each shippable on its own branch:

| Phase | Output | Days |
|---|---|---|
| DF1 | FastAPI ROUTE extractor + SQLAlchemy READS_FROM/WRITES_TO | 3 |
| DF2 | React FETCH_CALL extractor | 2 |
| DF3 | Stitcher + 4-step URL matcher with confidence scores | 2 |
| DF4 | CLI `dataflow trace`/`visualize`, MCP `dataflow_trace`, dashboard Sankey | 3 |

**Recommendation:** dispatch DF1 as a single background agent next week. Don't mix it into today's lane — it'll thrash the resolver/parser surface that A is fixing.

---

## Risk register

| Risk | Mitigation |
|---|---|
| A.R1 merge conflict with B in `parsers/python.py` | Worktrees. Different functions. Verified by F's read of the parser. |
| C 3D view CDN load failure on demo day | Lib has UMD fallback + plan §7 graceful fallback to 2D focus graph |
| PyPI name `codegraph-py` taken at upload | Plan E §1: manual twine upload first locks the name before automation runs |
| Resolver fix accidentally drops legit edges | Test fixtures in `tests/test_resolve.py` are the regression surface; CI runs pre-merge |
| Demo records 0 dead code after B fix → looks broken | Plan E §2: demo against codegraph itself which still has 2 false-positive cycles + 35-ish hotspots — narrative survives |
| LinkedIn post gets "this is just GitNexus lite" comment | Pinned comment owns the comparison upfront. Don't claim novelty. v0.2 wedge is the real answer. |

---

## What needs YOU specifically (not delegable)

1. **Approve Wave 1 dispatch** (one word: go)
2. **Record the demo** (2 hours, OBS) — could be later in day
3. **PyPI token** + `gh secret set` (15 min, your account)
4. **Push the v0.1.0 tag** (1 command)
5. **Post on LinkedIn** + cross-post (30 min)

Items 2–5 are **after** Wave 3 verification passes. If verification fails, we hold the post.

---

## Honest call on scope

- **In for today (T1):** F + A.R1 + B (Python only) + C + E.publish + E.post.
- **Out for today, in for v0.1.1 next week:** A.R2 (TS path aliases), B.D2 (TS NestJS decorators), B.D3 (config-driven custom decorators), `app.js` 4-way split.
- **Out for today, in for v0.2:** D.dataflow (full 2-week build).
- **Permanently out / not building:** rewrites, replacing the SQLite store, switching to embeddings (that's `better-code-review-graph`'s lane), competing head-on with GitNexus on generic code-graph features.

---

## Plans index

- `PLAN_CLEANUP.md` — F: ship-blockers, ~20 min
- `PLAN_DEADCODE.md` — B: decorator-aware roots, ~half day
- `PLAN_RESOLVER.md` — A: drop unresolved-edge rate to <25%, 1 day
- `PLAN_3D_VIEW.md` — C: 3d-force-graph view + demo loop, 1 day
- `PLAN_LAUNCH.md` + `draft_linkedin.md` — E: PyPI + post + strategy, 1 day mostly manual
- `PLAN_DATAFLOW.md` — D: v0.2 cross-stack data flow, 2 weeks
