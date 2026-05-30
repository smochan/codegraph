# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Removed

- **Dead `mcp.enabled` config block.** `.codegraph.yml` carried an
  `mcp.enabled: false` default that no code path ever read — confusing
  next to the active `register_mcp: true`. Removed from `CodegraphConfig`;
  the model is set to silently ignore the field so existing 0.1.x configs
  still load without error. New configs no longer emit it.

### Added

- **`codegraph clean` subcommand + auto-prune of `.codegraph/explore/`.**
  `codegraph serve` generated a pyvis HTML page per explored function
  and never pruned them — long-lived projects could grow this cache to
  hundreds of MB. New module `codegraph/cache_prune.py` implements LRU
  eviction by mtime (`prune_cache_to_size(path, max_size_mb)`), and the
  new `codegraph clean` subcommand exposes it with `--max-size-mb 50`
  (default) and `--all` (wipe everything). `codegraph serve` runs the
  prune on startup and prints the current cache size.
- **Auto-populate ignore patterns from detected ecosystem during `init`.**
  The free-text "Extra ignore patterns" prompt was a footgun — a user
  once typed `y` thinking it was yes/no and got `ignore: [- y]` in
  their YAML. Init now sniffs the repo for `pyproject.toml`,
  `package.json` (with React Native detection), `go.mod`, `Cargo.toml`,
  `pom.xml`, `build.gradle`, and pre-fills the matching ignore patterns
  (`__pycache__/`, `.venv/`, `node_modules/`, `ios/Pods/`,
  `android/build/`, `vendor/`, `target/`, `build/`, …). The user
  confirms the auto-detected list with a single yes/no; the free-text
  extras prompt is still there for project-specific paths but no longer
  the only path to safety.
- **`codegraph init` writes agent guidance to `CLAUDE.md` and `AGENTS.md`.**
  After a fresh install on a project, coding agents (Claude Code,
  Cursor, Codex, …) defaulted to grep even with polycodegraph's MCP
  server registered, because they had no hint that polycodegraph was
  available. Init now prompts (default: yes) and writes a short
  "`## polycodegraph`" section telling the agent which MCP tool to use
  for each kind of structural query (find-symbol, callers, callees,
  blast-radius, dataflow-trace, untested, dead-code). Mirrors the
  `.mcp.json` behaviour: creates the file when absent, appends when
  present without the section, leaves alone when the section is
  already there. Both files are written so Codex / GitHub Copilot CLI
  (which read `AGENTS.md`) get the hint too.

### Changed

- **Edge classification: `external` vs `unresolved-local`.** The
  `unresolved_edges` metric used to lump together imports of external
  packages (`fastapi`, `os`, `react`) — which static analysis without a
  venv/site-packages parse cannot resolve and isn't supposed to — with
  edges that pointed at in-repo symbols but couldn't be matched (rename
  drift, dynamic import). One number, two very different meanings.
  `compute_metrics` now also returns `external_edges` (root module not
  in the repo) and `unresolved_local_edges` (root is in-repo, symbol
  missed). The `unresolved_edges` total is kept as the sum for
  back-compat. Markdown report + MCP `metrics` tool both expose the
  split. (Surfaced by a user adding polycodegraph to a FastAPI project
  who saw "1,423 unresolved edges" and asked whether the tool was
  broken; almost all were external imports.)

### Fixed

- **`codegraph init` now writes a robust `.mcp.json`** — uses the absolute
  path to the `codegraph` binary (resolved from the running interpreter's
  bin dir, then `shutil.which`, then bare fallback), passes an explicit
  `--db .codegraph/graph.db` flag, and sets `cwd` to the repo root. The
  0.1.1 fix wrote the file but used a bare `codegraph` command with no
  `--db` and no `cwd`, which forced users to hand-edit the file when
  their MCP client's `$PATH` or working directory didn't line up. Old
  pre-0.1.2 default entries are migrated forward in place; user-customised
  entries are left alone. (Surfaced when a user added polycodegraph to a
  FastAPI project — Claude reported needing to fix all three.)
- **Type-annotation-only references no longer count as dead code.** The
  Python parser now emits a reference edge from a function/method to
  each capitalized type name appearing in its parameter and return type
  annotations. Edges go through the existing `unresolved::<TypeName>`
  resolver pipeline, so they rewrite to real `CLASS` ids when the type
  is defined in the repo. The flagship case is FastAPI Pydantic
  request-body models — `def create_defect(body: RetroDefect): ...` was
  flagged dead because the only reference to `RetroDefect` came through
  the type annotation; that loop is now closed. Stdlib typing
  scaffolding (`Optional`, `Annotated`, `Union`, …) and FastAPI
  dependency markers (`Body`, `Depends`, …) are blocklisted so the
  graph stays clean. Framework-agnostic: any function with type
  annotations benefits, not just route handlers.
- **MCP server returns an actionable error when the graph isn't built.**
  Previously, every tool would happily return an empty result against
  a missing `.codegraph/graph.db`. Claude / Cursor paraphrased that as
  "workspace is empty," sending users down the wrong rabbit hole. Now
  the dispatcher catches the missing-db case and returns a structured
  `{error: "graph_not_built", message: "polycodegraph: no graph found
  at <path>. Run \`codegraph build\` in the repo root first.", db_path:
  ...}`. New `GraphNotBuiltError` exposed from
  `codegraph.mcp_server.server` for callers that want to handle it
  explicitly.
- **`workspace_state` MCP tool now distinguishes "not configured" from
  "no repos".** When `~/.codegraph/workspace.yml` didn't exist, the
  tool returned `{workspace_size: 0, repos: []}` — indistinguishable
  from a configured-but-empty workspace. LLMs paraphrased this as
  "everything is broken" and cascaded into wrong-answer territory.
  Result now carries a `status` field
  (`workspace_not_configured` / `workspace_empty` / `ok`) with an
  actionable message: "local-graph MCP tools work independently — this
  only affects cross-repo tools. Run `codegraph workspace init` …".

## [0.1.1] — 2026-05-24

### Fixed

- **`codegraph init` now actually writes `.mcp.json`** when the user accepts
  the "Register MCP server" prompt. Previously the prompt was labelled
  "Phase 3 implementation" and only stored `register_mcp: true` in
  `.codegraph.yml` while doing nothing on disk — which meant the README's
  "Claude Code and Cursor auto-pick up polycodegraph" claim was broken in
  0.1.0. Init now writes a project-local `.mcp.json`, merges into an
  existing file when present, and preserves any user-customised `codegraph`
  entry it already finds. The prompt default also flipped from `False` to
  `True`. (Issue surfaced when a user ran `pipx install polycodegraph` on
  a fresh project and Cursor saw no MCP server.)

### Upgrading from 0.1.0

If you ran `codegraph init` on 0.1.0 and answered **yes** to the MCP
register prompt, your `.codegraph.yml` says `register_mcp: true` but no
`.mcp.json` was ever written. **Re-run `codegraph init`** after upgrading
— it will re-prompt (defaults are pre-filled from your existing config)
and now actually write the file. Your existing graph + config are
preserved.

### Post-launch-sprint additions (still pre-release)

#### Go language support — `.go` files parse + analyze cleanly

The Go ecosystem is the single biggest community pull outside Python/JS,
and a code graph that spans services + tooling + libraries was the
obvious next move. v1 of the Go extractor lives at
`codegraph/parsers/go.py` and produces the same node/edge shape as the
Python and TypeScript parsers, so every existing tool (`analyze`,
`workspace_blast_radius`, MCP queries) works on Go code immediately.

- **New module** `codegraph/parsers/go.py` — tree-sitter Go grammar via
  `tree-sitter-go>=0.23` (added to `pyproject.toml`).
- **Node kinds emitted**: `MODULE` (one per `.go` file, qualname = the
  `package X` name so files in the same package share an addressable
  namespace), `FUNCTION` (top-level `func`), `METHOD` (qualname
  `module.ReceiverType.Name`, with receiver + pointer-ness in metadata),
  `CLASS` (the closest analog to Go's `type X struct {...}` and
  `type X interface {...}`), `TEST` (`*_test.go` files).
- **Edge kinds emitted**: `DEFINED_IN`, `IMPORTS` (per-import-path,
  preserves aliases as metadata), `CALLS` (bare names like `Foo`,
  dotted-package like `fmt.Println`, receiver-method like `g.Greet`),
  `INHERITS` (Go composition — embedded fields in a struct become
  `INHERITS` edges to the embedded type).
- **Registry hookup**: `builder.py` imports `codegraph.parsers.go` at
  module load so the `@register_extractor` decorator fires. `init`'s
  language-detection map now includes `go: [".go"]`.
- **Smoke test against `spf13/cobra`**: 36 files parsed, 715 Go nodes
  (427 functions + 168 methods + 17 structs/interfaces + 17 test files
  + 19 modules), 2541 CALLS edges, 190 IMPORTS, 0 errors, 0.25s.
- **19 new parser tests** at `tests/test_go_parser.py` covering every
  emitted node/edge shape plus edge cases (empty file, missing file,
  test-file detection, aliased imports, pointer receivers).

Limitations the parser is honest about up front:

- Generic type parameters land as text in metadata; not in qualnames.
- Interface satisfaction (does `*Foo` implement `Bar`?) is not detected
  by the parser — that needs a whole-package pass and belongs in the
  resolver layer, not the extractor.
- `init()` and `main()` get no special treatment yet.

#### Cross-repo workspace mode — treat N repos as one mental unit

Solo devs and small teams routinely switch between 3–10 repos a day. Until
now `codegraph` was strictly single-repo — every command resolved against
the `.codegraph/graph.db` in the current working directory. The new
`codegraph workspace` subcommand group lets you register N repos once and
then query them as a union.

- **New CLI subcommands** (`codegraph/cli.py`):
  - `codegraph workspace init` — create `~/.codegraph/workspace.yml`
  - `codegraph workspace add <repo>` — register a repo (validates that the
    path exists and is a directory; idempotent)
  - `codegraph workspace remove <repo>` — deregister (the per-repo
    `.codegraph/graph.db` is untouched, only the membership)
  - `codegraph workspace list` — table of registered repos and whether
    each has a built graph
  - `codegraph workspace status` — per-repo git state: branch, dirty file
    count, last commit subject + timestamp, graph freshness, error notes
  - `codegraph workspace sync [--only <name>]` — rebuild the graph for
    every registered repo (or just one)
- **New module** at `codegraph/workspace/`:
  - `config.py` — `WorkspaceConfig` Pydantic model + YAML load/save with
    `CODEGRAPH_WORKSPACE_FILE` env-var override (useful for tests +
    per-shell workspaces)
  - `operations.py` — pure functions returning JSON-safe dicts so the CLI
    and MCP server share one implementation
- **3 new MCP tools** (`codegraph/mcp_server/server.py`):
  - `workspace_state()` — git + graph state for every registered repo
  - `workspace_diff_since(ref="main")` — cross-repo file changes since a
    git ref; combines committed (`<ref>...HEAD`) and uncommitted (`HEAD`)
  - `workspace_blast_radius(symbol, depth=None)` — unioned blast radius
    across all repos; reuses the existing single-repo `blast_radius()` so
    behaviour matches exactly per-repo
- **Pollution prevention** — workspace MCP tools self-load their per-repo
  graphs from the workspace config; the MCP `_call_tool` dispatch
  bypasses the usual `_load_graph()` for `workspace_*` names so the
  server doesn't materialize a stray `.codegraph/graph.db` in the cwd
  when the user only calls workspace tools.
- **Conflict handling** — when the same memory `id` exists on both sides
  with different bodies at the same `updated_at`, the conflicting remote
  copy is saved as `<id>.conflict-<timestamp>.md` next to the local
  file for manual merging. Sync never silently clobbers.
- **39 new tests** under `tests/test_workspace_{config,ops,cli,mcp}.py`
  covering config round-trip, real-tmp git-repo state probes,
  CliRunner-based CLI integration, and direct MCP handler invocation.
  Full suite remains green at 576 passing (was 537).
- **README updated** with a new "Cross-repo Workspace mode" collapsible
  block under CLI subcommands; MCP tools table now lists 18 total (was 15).

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
