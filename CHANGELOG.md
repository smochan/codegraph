# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

> 0.1.0 is in-progress / pre-release. The README, CLI, MCP server, and 3D
> dashboard reflect the current state of `main`, but the package has not yet
> been pushed to PyPI. Items below describe what has shipped on `main` and
> will roll into the eventual 0.1.0 tag. Install from source for now
> (`pip install -e .`).

### Post-launch-sprint additions (still pre-release)

#### v0.3 unified trace — Architecture view shows the real chain

- **Per-handler `dataflow` field on the HLD payload** (PR #22). Each route
  entry now carries a `dataflow.hops[]` array shaped to the v0.3 contract,
  so the dashboard can render the actual frontend → backend → DB chain
  without re-running analysis client-side.
- **Phase 4 of the Learn Mode lifecycle modal renders real hops** (PR #23).
  The previously-generic "project-specific data layer" phase now shows
  the actual handler → service → repo → model chain across **sequence,
  pipeline, and diagram** modes. Empty / low-confidence states render
  gracefully with a "no trace data" panel.
- **Argument-flow propagation — pick a parameter, watch it travel** (PRs #24,
  #25). Per-hop `arg_flow: dict[str, str | None]` mapping starting keys to
  their locally-renamed names. Frontend renders a chip-strip param picker
  and animates the selected param along the swimlane (sequence) or the
  bezier path (diagram, via SMIL `animateMotion`). Rename annotations
  (`(was userId)`) surface where the local name diverges. Snake_case ↔
  camelCase ↔ PascalCase all normalise to the same key.
- **ROUTE entry hop args backfilled from handler params** (PR #26). The
  trace walker can't supply args at the entry hop (no incoming CALLS edge),
  so URL-template handlers (e.g. `/api/users/{user_id}`) used to produce
  empty `arg_flow`. Backfilled from the handler node's DF0 `metadata.params`
  (skipping `self` / `cls`). Closes the launch demo's hero shot.

#### Cleanup + analyzer hardening

- **Examples directory excluded from dead-code / untested analysis**
  (PR #19) — `examples/cross-stack-demo` is documentation, not call-graph-
  traceable code.
- **Unused `_propagate_class_role_to_members` helper deleted** (PR #19).
- **`# pragma: codegraph-public-api` analyzer support** (PR #21). Functions
  and classes preceded by the pragma comment (Python `#` or TypeScript
  `//` style, with optional `# codegraph: public-api` alias) are exempted
  from `find_dead_code()`. Applied to all 15 known intentional public-API
  methods (`EmbeddingStore` facade, `SQLiteGraphStore.upsert_node` /
  `vacuum`, all `to_dict` / `as_dict` serializers, `_register.decorator`
  closure). **Self-graph dead-code count: 15 → 0**, honestly.

#### Docs & developer experience

- **README refresh** (PR #20). 15 MCP tools listed; DF1–DF4 + Architecture
  view documented in the headline feature list; "What it doesn't do yet"
  rewritten to drop already-shipped items; numeric stats current.
- **SESSION_HANDOFF.md** (PR #20) rewritten as a self-contained briefing
  for the next session.
- **`PLAN_V0_3_UNIFIED_TRACE.md`** (PR #20) — concrete spec for the unified
  trace work; now marked **shipped** as of PRs #22–#26.

#### Cross-stack data-flow tracing (DF0 → DF4)

- **DF0 — function signatures + per-call-site arguments.** Python and
  TypeScript parsers capture parameter lists, return-type annotations,
  and the literal text of each call-site argument and kwarg.
- **DF1 — HTTP routes + SQL data access.** FastAPI / Flask / aiohttp
  `ROUTE` edges; SQLAlchemy `READS_FROM` / `WRITES_TO` edges including
  `self.session.X` repository-pattern detection.
- **DF1.5 — role classification.** Functions and classes are tagged
  `HANDLER` / `SERVICE` / `COMPONENT` / `REPO` based on framework patterns.
- **DF2 — frontend `FETCH_CALL` extraction.** `fetch` / `axios` / `useSWR` /
  `useQuery` / api-client patterns emit `FETCH_CALL` edges with method,
  url, and body-key metadata.
- **DF3 — URL stitcher (`match_route`).** Stitches frontend `FETCH_CALL`
  URLs to backend `ROUTE` handlers with placeholder normalisation
  (`/users/{id}`, `${id}`, `:id`, numeric segments) and a body-key
  overlap bonus.
- **DF4 — `codegraph dataflow trace`.** Walks the call graph + cross-layer
  edges and emits an ordered `DataFlow`. Available as a CLI subcommand and
  the MCP `dataflow_trace` tool.

#### v0.3 embedding layer

- **`codegraph/embed/`** — chunker + embedder + LanceDB / JSON store.
- **`codegraph embed` CLI.** Default model `nomic-ai/CodeRankEmbed`
  (Apache 2.0, ~140 MB, 768-dim).
- **MCP tools** `semantic_search` and `hybrid_search`. Hybrid reranks
  embedding similarity by graph distance from a focus node.
- Optional install: `pip install -e ".[embed]"`.

#### 3D dashboard

- **3D focus-mode dashboard.** Pick any function from a role-grouped picker;
  trace ancestors and descendants; expand or collapse inline; always-on node
  labels via `three-spritetext`; color/role legend; hover signature tooltips;
  edge labels with call-site args; external calls render as terminal leaves.

#### MCP surface

- **15 tools registered.** `find_symbol` (with role filter), `callers`,
  `callees` (both surfacing params + role + per-call-site args),
  `blast_radius`, `subgraph`, `dead_code`, `cycles`, `untested`, `hotspots`,
  `metrics`, `semantic_search`, `hybrid_search`, `dataflow_routes`,
  `dataflow_fetches`, `dataflow_trace`.
- HLD payload exposes DF0 + DF1.5 + DF1 + DF2 metadata.

#### Resolver

- **R2 patterns.** Same-file constructor calls, decorator-call edges,
  class-annotation `self.X.Y` chains, and fresh-instance method calls
  are now resolved on Python.
- **R3 patterns.** Conditional `self.X` assignments (`if/else` branches)
  and class-level union annotations (`Foo | Bar`) bind to all candidate
  types.

#### Analysis & quality

- **Cycles with qualnames.** Both `analyze` and the MCP `cycles` tool
  resolve cycle node IDs to dotted qualnames.
- **Analyzer hardening.** Pure line-shift no longer triggers
  `modified-signature` findings (was producing 50+ false-positives on
  PRs that touched the top of high-traffic files like `app.js`).
- **Skip paths extended.** `tests/fixtures/`, `/static/`, and `examples/`
  are auto-excluded from dead-code and untested-function analysers.
- **Protocol classes** are no longer flagged as dead code.

#### CI & contributor experience

- **`codegraph PR review` GitHub Actions workflow.** Builds baseline from
  `origin/main`, builds PR head, runs `codegraph review`, posts sticky
  PR comment (or run-summary on fork PRs), fails the check on
  `--fail-on high`.
- **`ci.yml` self-explanatory failures.** Inline `::error` annotations on
  the Files tab; every failing step writes a step-summary block with the
  exact local-fix command.
- **`scripts/test-pr-review-locally.sh`** — emulates the CI review locally
  so contributors can pre-validate before pushing.
- **`CONTRIBUTING.md`** — covers setup, commit / PR conventions, branch
  protection, and the dogfood loop.
- **`examples/cross-stack-demo/`** — FastAPI + SQLAlchemy + React fixture
  exercising the full DF0 → DF4 chain. 9 regression tests assert it stays
  reproducible.

## [0.1.0] - in-progress

### Added

#### Core graph & storage
- SQLite-backed graph store with typed node/edge schema (file, class, function, variable, import, calls, inherits, tested-by)
- NetworkX adapter for in-memory graph operations (BFS, SCC, centrality)
- Incremental rebuild: only re-parses files whose mtime/hash has changed
- `codegraph init` — interactive setup: detects languages, configures ignore globs, optionally registers MCP server

#### Parsers
- Tree-sitter base extractor infrastructure with language dispatch table
- Python extractor: functions, classes, methods, variables, imports, calls
- TypeScript / TSX / JavaScript extractor: functions, classes, exports, imports, calls
- Pluggable design: adding a new language requires a single extractor file

#### Cross-file resolution
- Cross-file CALLS and IMPORTS resolver: links call-site nodes to definition nodes across the whole repo
- Handles Python relative imports and `from … import` forms
- Handles TypeScript path-based and package imports

#### Analysis
- Dead-code detection: unreferenced functions and classes with no incoming reference edges
- Import/call cycle detection via Tarjan SCC on the graph
- Hotspot ranking: callables scored by fan-in × 2 + fan-out + LOC/50
- Untested function detection: callables with no incoming CALLS from test modules
- Blast-radius query: transitive set of nodes referencing a given symbol
- Aggregate metrics: total nodes/edges, breakdown by kind, top files by node count

#### PR review
- Graph differ: computes added/removed/changed nodes and edges between two graph snapshots
- Risk scorer: weighted blast-radius and coupling score → 0–100 risk number
- YAML rule engine: user-defined rules matching on symbol patterns with configurable severity
- Output renderers: Markdown, JSON, SARIF (compatible with GitHub Code Scanning)
- `codegraph review` CLI command with `--format`, `--output`, `--baseline`, `--rules` flags
- `codegraph baseline save/status/push` for managing named baselines
- `codegraph hook install/uninstall` — pre-push git hook that auto-runs `codegraph review`

#### MCP server
- `codegraph mcp serve` — stdio-transport MCP server for Claude Code / any MCP client
- 10 curated tools: `find_symbol`, `callers`, `callees`, `blast_radius`, `subgraph`, `dead_code`, `cycles`, `untested`, `hotspots`, `metrics`
- Returns small, focused subgraphs — avoids flooding context windows
- Auto-registration option in `codegraph init` writes `.mcp.json` to project root

#### Web dashboard
- `codegraph serve` — local web dashboard (Starlette, no JS framework)
- Overview tab: node/edge counts, language breakdown, top files, dead code summary
- Architecture tab: interactive dependency matrix and Sankey flow diagram
- Call graph tab: force-directed interactive graph (pyvis)
- Inheritance tab: class hierarchy diagram
- HLD (High-Level Design) tab: layered architecture navigator with animated focus graph
- Collapsible sidebar, light/dark theme toggle, responsive layout

#### Visualisation
- `codegraph viz` — render graph as Mermaid diagram, interactive pyvis HTML, or Graphviz SVG
- `codegraph explore` — terminal interactive subgraph explorer
- Graceful fallback when optional `graphviz` system package is absent
- Mermaid clustering by module, density cap to avoid browser freezes

#### CLI & packaging
- Top-level `codegraph` command with `--version` and `--data-dir` flags
- `codegraph build --incremental` for fast re-runs on large repos
- `codegraph status` for a quick health summary
- `codegraph query` sub-commands: `callers`, `subgraph`, `deadcode`, `untested`, `cycles`
- `py.typed` PEP 561 marker so downstream type-checkers see type information
- Wheel includes `codegraph/web/static/` assets so `codegraph serve` works after `pip install`
- MIT licensed, zero telemetry, fully offline capable
