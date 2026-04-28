# Session Handoff — codegraph (post-DF4 + Architecture view + CI hardening)

**Last update:** 2026-04-28
**Repo:** /media/mochan/Files/projects/codegraph
**Branch where work is happening:** `main` (PR-only merges; branch protected)
**HEAD on main as of writing:** `f8bbd56` — `merge: feat(web): 3D force-directed graph view (vasturiano/3d-force-graph)`
**Public remote:** https://github.com/smochan/codegraph (public, branch-protected)

---

## TL;DR

`codegraph` is a tree-sitter → SQLite code graph + CLI + web dashboard
(3D focus view + Architecture view) + MCP server, with cross-stack data-flow
tracing (DF1 → DF4) and a local embeddings layer. The 0.1.0 launch work is
complete on `main`; PyPI publish is deferred until the v0.3 unified trace
sprint ships. **487 tests pass (484 Python + 3 skipped HLD-on-real-graph).
0 open PRs. 15 MCP tools. 15 dead-code findings on the self-graph. 3 cycles.**

The space is crowded — GitNexus, code-review-graph, better-code-review-graph,
JudiniLabs/mcp-code-graph, sdsrss/code-graph-mcp, RepoMapper, Graphify. Our
defensible wedge: decorator-aware dead code + role classification + DF0
argument capture + 3D focus tracer + Architecture / Learn Mode lifecycle UI +
DF4 cross-stack `dataflow trace`.

---

## What landed since the last handoff

Group by sprint, with PR numbers as anchors.

### Cross-stack data-flow tracing (DF1 → DF4)

- **DF1 — HTTP routes + SQL data access.** FastAPI / Flask / aiohttp `ROUTE`
  edges; SQLAlchemy `READS_FROM` / `WRITES_TO` for `session.query` /
  `Model.query` / `session.add` / `session.execute(select|insert|update|delete)`.
  New `dataflow_routes` MCP tool. Demo + tests in PRs **#5 prep, #6, #7, #8**.
- **DF1.5 — role classification** (`HANDLER` / `SERVICE` / `COMPONENT` / `REPO`)
  for HTTP frameworks; HLD payload exposes role per node.
- **DF2 — `FETCH_CALL` extraction** for `fetch` / `axios` / `useSWR` /
  `useQuery` / `apiClient.*`, with body-key metadata.
- **DF3 — URL stitcher (`match_route`)** with placeholder normalisation
  and body-key overlap bonus.
- **DF4 — `codegraph dataflow trace` CLI + `dataflow_trace` MCP tool.**
  Walks call graph + cross-layer edges and emits an ordered `DataFlow` of
  hops from frontend through handler → service → repo → SQL target.

### v0.3 embeddings layer (merged earlier this week)

- `codegraph/embed/` — chunker, embedder, LanceDB / JSON store.
- `codegraph embed` CLI. Default model `nomic-ai/CodeRankEmbed`
  (Apache 2.0, ~140 MB, 768-dim, code-tuned).
- MCP tools `semantic_search` and `hybrid_search`. Hybrid reranks by
  graph distance from a focus node: `0.6 · cosine + 0.4 · 1/(1+hops)`.
- Optional install via `pip install -e ".[embed]"` — does not bloat default.

### Cleanup PRs (3)

- **R3 resolver** — conditional `self.X` assignments + class-level union
  annotations bind to all candidate types.
- **Analyzer cleanup** — orphaned `propagate` helper deleted, unused
  `_strip_string_literal` and `_module_id_for_file` helpers removed
  (`fd9a8bd`, `71ed2b5`, `96bdc1c`).
- **Helper coverage** — added regression tests around resolver / analyzer
  helpers, ruff + mypy clean (`d4c98c4`).

### PR review CI hardening

- **#16** — `fix(ci): pr-review fork-PR support, baseline-pollution, release validator`.
  Fork PRs now post a Run-Summary block instead of crashing on missing
  `secrets.GITHUB_TOKEN` write scope; baseline build no longer pollutes
  the PR-head graph.
- **#17** — `fix(ci): self-explanatory failures (annotations + step summary)`.
  Inline `::error` annotations on the Files tab; every failing step writes
  the exact local-fix command.
- **#18** — `fix(review): line-shift no longer triggers modified-signature finding`.
  Pure top-of-file additions used to flag every function below as
  "signature changed"; differ now compares signature *text*, not line
  numbers. Cut false-positive rate ~50× on `app.js`-touching PRs.

### Architecture view + Learn Mode lifecycle modal

- **#15** (external contributor — Arijit) —
  `feat(architecture): add infrastructure detection + Architecture dashboard view`
  plus `feat(architecture): add Pipeline + Diagram visualizations to lifecycle modal`.
  Adds `codegraph/analysis/infrastructure.py` (web framework / ORM / cache /
  queue / external-HTTP detection) and a new Architecture tab in the web
  dashboard. The Learn Mode modal animates the full request lifecycle —
  TCP handshake → TLS → HTTP → data layer → response — as either a sequence
  diagram or a pipeline view. Mode persists across modal opens via
  `localStorage`. **Phase 4 ("project-specific data layer") is currently
  generic placeholder content** — wiring DF4's real `DataFlow` into Phase 4
  is the v0.3 unified-trace sprint (see
  [`PLAN_V0_3_UNIFIED_TRACE.md`](./PLAN_V0_3_UNIFIED_TRACE.md)).

### Skip examples/ + CHANGELOG refresh

- **#19** — `chore(analysis): skip examples/ + delete orphaned propagate helper + refresh CHANGELOG`.
  `tests/fixtures/`, `/static/`, and `examples/` are now auto-excluded
  from dead-code and untested-function analysers. CHANGELOG brought in
  line with current `main` — it's the source of truth for "what we have."

---

## Current state numbers

| Metric                | Value                                  |
|-----------------------|----------------------------------------|
| Tests passing         | 484 Python + 3 skipped = **487 total** |
| Dead code (self-graph)| **15** (was 24+, was 451)              |
| Cycles (self-graph)   | **3** (all documented & accepted)      |
| MCP tools registered  | **15**                                 |
| Open PRs              | 0                                      |
| Languages parsed      | Python, TypeScript, TSX, JavaScript    |
| Self-graph nodes      | 3,178                                  |
| Self-graph edges      | 7,229                                  |

The 3 cycles: dashboard UI redraw loop (`hldRenderNav → jumpToQualname →
drawFocusGraph` — deliberate), parser self-recursion (`_handle_class →
_visit_nested_defs → _handle_function` — intentional traversal), and the
MCP `_serve ↔ run` static-resolver false positive.

---

## What's deferred and why

| Item                                     | Why deferred                                           | Target |
|------------------------------------------|--------------------------------------------------------|--------|
| Argument-flow propagation (`user_id` traced through hops) | Needs identity-tracking pass on top of DF0 args        | v0.3   |
| Unified trace UI (DF4 → Learn Mode Phase 4)               | Spec written this session — see PLAN_V0_3_UNIFIED_TRACE | v0.3   |
| Mypy / Pyright type inference                             | Heavy lift; not blocking 0.1.x users                   | v0.3+  |
| TS R2 resolver (path aliases, fresh-instance binding)     | Python parity ships first; TS less critical for 0.1.0  | v0.1.2 |
| Typer CLI symbols classified `HANDLER`                    | DF1.5 only handles HTTP frameworks today               | v0.1.x |
| Benchmarks (CrossCodeEval + SWE-bench Lite)               | $$$ — held until PyPI publish                          | post-launch |
| PyPI publish + LinkedIn launch                            | Held until unified trace ships so demo is end-to-end   | v0.3   |

---

## First action for next session

After context reset, start with the v0.3 unified-trace sprint:

1. Read [`PLAN_V0_3_UNIFIED_TRACE.md`](./PLAN_V0_3_UNIFIED_TRACE.md) — the
   plan written this session.
2. Open `codegraph/web/static/views/architecture.js` and locate Phase 4
   (search for `// ---- Phase 4: Project-specific data layer`, around
   line 303). That block is the wiring point.
3. Open `codegraph/analysis/infrastructure.py` and confirm the existing
   per-handler payload shape — Phase 4 will need DF4's `DataFlow` joined
   onto each handler entry.
4. Run `./scripts/test-pr-review-locally.sh` first to confirm baseline
   review on `main` is clean before opening a PR.

Branch protection on `main` requires PR-only merges, so all v0.3 work
goes through a feature branch + sticky-comment review.
