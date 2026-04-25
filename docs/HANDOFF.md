# codegraph — handoff / continuation guide

> Read this first when resuming work in a new session. This doc is the source of truth
> for project status, architecture decisions, and what to do next.

## TL;DR for a new session

1. Open the repo: `cd "/Users/B0317090/Desktop/Explore projects/codegraph"`.
2. `source .venv/bin/activate` (Python venv with all deps installed).
3. Read **this file** + `docs/plan.md` + `docs/phase1-smoke.md`.
4. Check open work: `sqlite3 ./scratch-todo` is not used here — todo state lives in the
   chat session DB, not the repo. The remaining phases are documented in **"Phase status"**
   below; that's the canonical list when starting fresh.
5. Pick a phase, dispatch a sub-agent or implement directly. Always commit with the
   `Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>` trailer.

## Project identity

- **Name**: `codegraph`
- **PyPI distribution name**: `codegraph-py` (`codegraph` is taken on PyPI by an unrelated tool)
- **CLI command**: `codegraph`
- **Import package**: `codegraph`
- **License**: MIT
- **GitHub**: https://github.com/smochan/codegraph (public)
- **Local path**: `/Users/B0317090/Desktop/Explore projects/codegraph`
- **Local git identity** (this repo only): `mochan <smochan07@gmail.com>` —
  set via `git config user.email/user.name`. Global git identity is unchanged
  (company id `Sankat.Mochan@airtel.com`). Do not change global config.
- **GitHub auth**: `gh` CLI is logged into both `smochan` (active) and `B0317090_airtel`.
  The active account `smochan` is what powers pushes. Verify with `gh auth status`.

## What is codegraph?

A language-agnostic code graph builder + analyzer + PR risk reviewer + MCP server for
Claude Code. Parse a repo with tree-sitter, build a queryable graph of
files/classes/functions/variables/imports/calls/inheritance/tests, then use it to:

- analyze the whole project (dead code, cycles, untested hot paths, fan-in/out)
- review PRs by diffing your branch's graph against a baseline and scoring blast radius
- visualize the graph (Mermaid / interactive HTML / SVG)
- power AI assistants via an MCP server that returns *small, focused subgraphs*

The motivating use case: replace the bespoke, Oracle-coupled, Python-only
`pre_pr_review` tool from `whatsappbottestingagent` with a portable open-source
package usable on any repo (canary repos: `calybe` for TS/RN, `whatsappbottestingagent`
for Python).

## Phase status

| Phase | Title | Status |
|---|---|---|
| 0 | Repo bootstrap | ✅ done |
| 1 | Core graph MVP (schema, SQLite, Python+TS extractors, init/build/status/viz) | ✅ done |
| 2 | Language breadth (JS, Go, Java, Rust, C#, Ruby, PHP) | ⬜ pending |
| 3 | Analysis (blast_radius, dead_code, cycles, untested, hotspots, metrics, `analyze`) | ✅ done |
| 4 | PR review (differ, YAML rules, risk scorer, baseline backends, git hook) | ⬜ pending |
| 5 | MCP server for Claude Code (`mcp serve` + curated subgraph tools) | ⬜ pending |
| 6 | Visualization polish (pyvis HTML, graphviz SVG, richer Mermaid) | ✅ done |
| 7 | Open-source release (PyPI publish, README polish, examples, v0.1.0 tag) | ⬜ pending |

Dependencies: 2,3,6 depend on 1; 4 depends on 3; 5 depends on 3; 7 depends on 2,4,5,6.

## What's actually shipped (Phase 0 + 1)

### File map

```
codegraph/
├─ pyproject.toml                  # hatchling, deps, ruff, mypy strict, pytest
├─ LICENSE                         # MIT
├─ README.md
├─ .gitignore
├─ .github/workflows/ci.yml        # 3.10 / 3.11 / 3.12 matrix, lint+mypy+pytest
├─ docs/
│  ├─ plan.md                      # full phased roadmap
│  ├─ phase1-smoke.md              # canary-repo numbers (calybe + whatsappbot)
│  └─ HANDOFF.md                   # ← you are here
├─ codegraph/
│  ├─ __init__.py                  # __version__ = "0.0.1"
│  ├─ cli.py                       # typer app, real impls for init/build/status/viz
│  ├─ config.py                    # CodegraphConfig (pydantic) + load/save .codegraph.yml
│  ├─ graph/
│  │  ├─ __init__.py
│  │  ├─ schema.py                 # NodeKind, EdgeKind, Node, Edge, make_node_id
│  │  ├─ store_sqlite.py           # SQLiteGraphStore (WAL, FK on, indexes)
│  │  └─ store_networkx.py         # to_digraph, subgraph_around
│  ├─ parsers/
│  │  ├─ __init__.py
│  │  ├─ base.py                   # ExtractorBase, parser cache, registry
│  │  ├─ python.py                 # tree-sitter-python extractor
│  │  └─ typescript.py             # tree-sitter-typescript / tsx / javascript
│  └─ graph/builder.py             # GraphBuilder, BuildStats, ignore patterns
└─ tests/
   ├─ test_cli_smoke.py            # CLI wiring smoke
   ├─ test_schema.py
   ├─ test_store_sqlite.py
   ├─ test_networkx_adapter.py
   ├─ test_extractor_python.py
   ├─ test_extractor_typescript.py
   ├─ test_builder.py
   ├─ test_cli_init_build.py
   └─ fixtures/
      ├─ python_sample/
      └─ ts_sample/
```

### CLI surface (already wired)

Real impls — work end-to-end:

```
codegraph init [--non-interactive]
codegraph build [--incremental/--no-incremental]
codegraph status
codegraph viz --out mermaid [--scope <path-or-symbol>]
```

Stubs (return TODO message):

```
codegraph analyze
codegraph review
codegraph query {callers|subgraph|untested|deadcode|cycles}
codegraph baseline push
codegraph hook {install|uninstall}
codegraph mcp serve
```

### Known canary-repo numbers (sanity check — re-run anytime)

| Repo | Files scanned | Files parsed | Nodes | Edges | Build time |
|---|---:|---:|---:|---:|---:|
| `calybe` (TS/RN) | 11,609 | 293 | 12,297 | 4,324 | ~14s |
| `whatsappbottestingagent` (Py) | 29,087 | 296 | 30,666 | 12,723 | ~32s |

If new numbers are dramatically lower, suspect: ignore globs too aggressive, missing
extractor dispatch, or tree-sitter grammar regression.

### Test / quality status at handoff

- `pytest -q` → **73 passed / 0 failed**
- `ruff check codegraph tests` → clean
- `mypy codegraph` (strict) → clean
- CI on `main` → green ([latest run](https://github.com/smochan/codegraph/actions))

## Architectural decisions (for new-session context)

1. **Pydantic v2** for all schemas. No dataclasses for shipped data types. JSON
   round-trip via `model_dump_json` / `model_validate_json`.
2. **SQLite + WAL + FKs ON** as default store. Path: `<repo>/.codegraph/graph.db`.
   Composite PK on edges `(src, dst, kind)`. Indexes on hot columns.
3. **NetworkX MultiDiGraph** as the in-memory analysis representation. Edges keyed
   by `EdgeKind.value` so multiple edge kinds between the same pair are preserved.
4. **tree-sitter** is the only parsing tech. The agent that delivered Phase 1 found
   that `tree-sitter-language-pack` had TLS download issues on this machine, so we
   pin **individual** grammar packages (`tree-sitter-python`, `tree-sitter-typescript`,
   `tree-sitter-javascript`) directly in `pyproject.toml`. New languages should follow
   the same pattern: add the per-language package, write an extractor that subclasses
   `ExtractorBase`, register via `@register_extractor`.
5. **Cross-file CALLS resolution is deferred.** Extractors emit `dst="unresolved::<name>"`
   sentinels. Phase 3 will add a resolution pass that turns these into real node ids
   using the module/import graph.
6. **Ignore patterns**: built-ins always include `.git`, `.venv`, `venv`, `node_modules`,
   `.codegraph`, `dist`, `build`, `__pycache__`, `.next`, `.pytest_cache`, `.mypy_cache`,
   `.ruff_cache`. User additions live in `.codegraph.yml`. Implementation uses `pathspec`
   with `gitignore` syntax.
7. **Incremental build**: SHA-256 of file content stored on the FILE node. If unchanged,
   skip. If changed, `delete_file()` cascades all that file's nodes/edges, then re-parse.
8. **Test detection**: in-band — extractor sets `metadata.is_test=true` on the MODULE
   node (Python: `tests/**`, `test_*.py`, `*_test.py`; TS: `**/*.{test,spec}.{ts,tsx,js,jsx}`,
   `__tests__/`).
9. **Strict mypy** is non-negotiable. Use `cast()` and TypedDict over `# type: ignore`.
   Sparing `# type: ignore[<code>]` is acceptable for tree-sitter `Node.text`/`children`
   typing only.
10. **No tokens in files. No global git config changes. No edits outside the repo.**
    All gh interactions use the `gh` CLI's own keyring.

## How to resume cleanly in a new session

The new session should be opened **with `/Users/B0317090/Desktop/Explore projects/codegraph`
as the working directory** (not the calybe repo). Then:

```bash
source .venv/bin/activate
git status            # confirm clean
git pull              # in case CI / other clones pushed
pytest -q             # confirm 40 passing
gh run list --limit 1 # confirm CI green
```

Then tell the agent which phase to tackle. Suggested prompt:

> "Open `docs/HANDOFF.md`. We finished Phase 0 + Phase 1. Now deliver
> **Phase <N>: <title>** end-to-end, following the same standards: real
> implementations, tests passing, ruff + mypy strict clean, CI green, well-organized
> commits with the Copilot co-author trailer, push to `origin main`."

## Phase entry points (cheat sheet for next sessions)

### Phase 2 — language breadth
- Add `tree-sitter-go`, `tree-sitter-java`, `tree-sitter-rust`, `tree-sitter-c-sharp`,
  `tree-sitter-ruby`, `tree-sitter-php` to `pyproject.toml`.
- Mirror `parsers/python.py` pattern: one file per language extending `ExtractorBase`
  + `@register_extractor`.
- Each language: emit MODULE/CLASS/FUNCTION/METHOD nodes, IMPORT/CALLS/INHERITS edges,
  test-file metadata. Cross-file resolution still deferred.
- Add 2-3 file fixtures + extractor unit tests per language.
- Sub-agents can fan out one-per-language; they're independent.

### Phase 3 — analysis
- ✅ Implemented in `codegraph/analysis/` — `blast_radius.py`, `dead_code.py`,
  `cycles.py`, `untested.py`, `hotspots.py`, `metrics.py`, plus `report.py`
  (markdown / json renderer + `find_symbol`).
- ✅ Cross-file resolution lives in `codegraph/resolve/calls.py`. It runs
  automatically at the end of every `GraphBuilder.build()`. Strategy:
  exact qualname → same-module → import binding → unique tail-match → unique
  bare-name. Anything ambiguous is left as `unresolved::*` so analyses stay
  safe.
- ✅ CLI wired: `codegraph analyze [--format markdown|json] [--output FILE]
  [--hotspots N]` and `codegraph query {callers|subgraph|untested|deadcode|
  cycles}` — see `tests/test_cli_analyze_query.py` for usage.
- Store gained `delete_edge(src, dst, kind)` and `count_unresolved_edges()`.

### Phase 4 — PR review
- `codegraph/review/differ.py` — diff two SQLite graphs (or a graph vs a baseline JSON).
- `codegraph/review/rules_engine.py` — load YAML rule packs from `codegraph/rules/defaults/`
  + user rules from config; per-pattern weight, require_tests, protected, checks.
- `codegraph/review/risk_scorer.py` — verdict mapping LOW/MEDIUM/HIGH/CRITICAL.
- `codegraph/baseline/{base,local,s3,sql}.py` — pluggable storage. `local` first
  (gzip JSON of nodes+edges in `.codegraph/baselines/<branch>.json.gz`).
- `codegraph hook install` — write `.git/hooks/pre-push` that runs `codegraph review`.

### Phase 5 — MCP server
- `codegraph/mcp/server.py` using the `mcp` Python SDK (already in optional deps).
- Tools to expose: `find_symbol`, `get_callers`, `get_callees`, `get_blast_radius`,
  `get_subgraph`, `find_untested`, `find_dead_code`, `find_cycles`, `summarize_file`.
- All tools cap responses (default 200 nodes, opt-in `full=true`).
- During `init` (when user says yes to MCP), append a `codegraph` server entry to
  `~/.config/Claude/claude_desktop_config.json` and project-local `.mcp.json` if present.

### Phase 6 — viz polish
- ✅ `codegraph/viz/` package: `mermaid.py` (file-clustered, kind-colored,
  edge-styled flowchart with a built-in legend), `html.py` (pyvis interactive
  graph with Barnes-Hut layout, hover-tooltips, dark theme), `svg.py`
  (graphviz-backed; raises ``GraphvizUnavailableError`` if `dot` or the
  `graphviz` package is missing so the CLI degrades gracefully).
- pyvis is now a required dependency; graphviz remains optional under the
  `viz` extra.
- CLI: `codegraph viz --out {mermaid,html,svg} [--output PATH] [--scope X]
  [--limit N] [--no-cluster]`.

### Phase 6.5 — multi-view explorer dashboard
- ✅ `codegraph/viz/explore.py` builds a folder of linked HTML pages so a real
  repo can be browsed at multiple zoom levels:
  - `index.html` — hand-rolled dashboard: project metrics, breakdowns by node /
    edge kind / language, top hotspots, links to every other view.
  - `architecture.html` — module-level diagram. CLASS/FUNCTION/METHOD nodes
    are collapsed into their parent MODULE; CALLS+IMPORTS+INHERITS edges are
    aggregated with `weight=count` and rendered with proportional thickness
    plus an `xN` label.
  - `callgraph.html` — only FUNCTION/METHOD nodes + CALLS edges. Each node is
    sized by fan-in (callers); top-N degree-ranked when over the cap.
  - `inheritance.html` — only CLASS nodes + INHERITS/IMPLEMENTS edges.
  - `files/<slug>.html` — one detail page per top-N most populated file,
    showing the file's symbols + 1-hop neighbours so cross-file calls remain
    in context.
- Every pyvis page exposes the built-in `select_menu` + `filter_menu` so users
  can search by qualname or filter by group/file/language without leaving the
  page. All pages use `cdn_resources="in_line"` so the folder works over
  `file://` with no server.
- `unresolved::*` ghost nodes and FILE nodes are stripped before rendering so
  drawings reflect the *real* graph.
- CLI: `codegraph explore [--output DIR] [--top-files N] [--callgraph-limit N]`.
  Default output `.codegraph/explore/`.

### Phase 7 — release
- Bump to `0.1.0`. Tag on GitHub. Publish to PyPI (`hatch build`, `hatch publish`
  or `uv build` + `twine`). Update README with badges + screenshots. Add `examples/`.

## Open decisions deferred to later phases

- Baseline backend defaults: local file is fine for OSS. S3 / SQL require user creds
  and config UX.
- MCP auto-registration: ask in `init`; if accepted, write to project `.mcp.json`
  rather than global Claude config (less invasive, version-controlled per-project).
- Should `analyze` write a markdown report to `docs/codegraph-report.md` by default,
  or only stdout? — proposal: stdout by default, `--output <path>` to write.
- Component detection in TS: Phase 1 treats components as plain functions. A future
  phase could mark JSX-returning functions as `kind=COMPONENT` (would need new NodeKind).

## Useful commands

```bash
# develop
source .venv/bin/activate
pytest -q
ruff check codegraph tests
mypy codegraph

# run on a real repo (e.g. calybe) without polluting it
mkdir -p /tmp/codegraph-calybe-data
cd /Users/B0317090/Desktop/Projects/ios/calybe
codegraph init --non-interactive   # writes .codegraph.yml in calybe (commit/ignore as desired)
codegraph build
codegraph status
codegraph viz --out mermaid > /tmp/calybe.mmd

# list phase status quickly
git log --oneline
gh run list --limit 5
```

## Phase 5 — MCP server (`codegraph mcp serve`)

### How to launch

```bash
# In any repo that has a built graph:
codegraph mcp serve                           # auto-resolves .codegraph/graph.db
codegraph mcp serve --db path/to/graph.db    # explicit db path
codegraph mcp serve --name my-project        # custom server name (default: codegraph)
```

The server uses the **stdio transport** (JSON-RPC over stdin/stdout) and is
compatible with Claude Code, Claude Desktop, and any MCP client.

### Claude Code config snippet

Add to your Claude Code MCP config (usually `~/.claude.json` or via `claude mcp add`):

```json
{"mcpServers":{"codegraph":{"command":"codegraph","args":["mcp","serve","--db",".codegraph/graph.db"]}}}
```

### Exposed tools

| Tool | Description |
|------|-------------|
| `find_symbol` | Substring search for symbols by qualname; optional `kind` filter, `limit` |
| `callers` | Reverse BFS from a symbol — who calls it? (configurable `depth`) |
| `callees` | Forward BFS from a symbol — what does it call? (configurable `depth`) |
| `blast_radius` | Set of nodes transitively referencing a symbol (wraps `analysis.blast_radius`) |
| `subgraph` | Induced subgraph of listed symbols expanded `depth` hops over CALLS+IMPORTS+INHERITS |
| `dead_code` | Unreferenced functions/classes with no incoming reference edges |
| `cycles` | Import and call strongly-connected-components (cycles) |
| `untested` | Functions/methods with no incoming CALLS from a test module |
| `hotspots` | Top-N callables ranked by fan-in × 2 + fan-out + LOC/50 |
| `metrics` | Aggregate counts: total nodes/edges, breakdown by kind, top files |

### Implementation notes

- Module: `codegraph/mcp_server/server.py` (kept under `mcp_server/` to avoid shadowing the `mcp` SDK)
- Tool handlers are pure functions `(graph, **args) -> dict|list` — fully testable without MCP machinery
- Graph is loaded once per process and cached; pass `--db` to reload from a different path
- 14 new tests in `tests/test_mcp_server.py`

## When resuming: tell the agent

A good resume prompt:

> Read `docs/HANDOFF.md` and `docs/plan.md`. We finished Phase 0, 1, 3, 5,
> and 6 (108 tests passing, CI green). Now deliver the remaining phases
> following the same standards: real implementations, tests passing,
> ruff + mypy strict clean, CI green, well-organized commits with the
> Copilot co-author trailer, push to `origin main`.

## Phase 4 — PR review (delivered)

Phase 4 wires up risk-scored PR review on top of the existing graph store.

**Modules** (`codegraph/review/`)

- `baseline.py` — `save_baseline(db_path, baseline_path)` copies the live
  `graph.db` aside; `load_baseline(path)` returns a `nx.MultiDiGraph` (or
  `None`).
- `differ.py` — `diff_graphs(old, new)` produces a `GraphDiff` with
  `added/removed/modified_nodes` and `added/removed_edges`. Node identity is
  `(qualname, kind)`; *modified* means same key but different
  `file/line_start/signature` (with `details = {field: {old, new}}`).
- `risk.py` — `score_change(change, *, new_graph, old_graph, extra=...)`
  returns a `Risk(score, level, reasons)`. Heuristics: high fan-in (+40),
  removed-still-referenced (+50), in-hotspot-file (+20), new dead code (+10),
  signature param-count change (+20), introduces-cycle (+30). Cap 100.
  Levels: low ≤ 20, med 21–50, high 51–80, critical ≥ 81.
- `rules.py` — `Rule` schema with `when` ∈ {`added_node`, `removed_node`,
  `modified_node`, `removed_referenced`, `introduces_cycle`, `high_fan_in`,
  `new_dead_code`} plus `match` filters (kind / qualname prefix / regex /
  file glob). `load_rules(path | None)` reads YAML or falls back to
  `DEFAULT_RULES`. `evaluate_rules(diff, ...)` returns sorted `Finding`s.
- `hook.py` — `install_hook / uninstall_hook / is_installed` writing a
  marker-tagged shell script under `.git/hooks/`.

**CLI**

- `codegraph baseline save [-o PATH]` / `codegraph baseline status` /
  `codegraph baseline push --target <branch>` (CI-friendly alias).
- `codegraph review --target main --block-on high --fail-on high
  --baseline PATH --format markdown|json|sarif --output FILE
  --rules PATH`. Exit 0 = no blocking findings, 1 = blocking findings or
  build error, 2 = no baseline.
- `codegraph hook install [--hook pre-push] [--target main] [--force]` and
  `codegraph hook uninstall`.

**Fixtures + tests**

- `tests/fixtures/python_sample_v2/` mirrors `python_sample` but mutates
  `Dog.speak` (adds `loud: bool = False`), removes `Dog.fetch`, and adds
  `utils.new_function`.
- `tests/test_review_differ.py`, `test_review_risk.py`,
  `test_review_rules.py`, `test_review_cli.py` — 22 new tests covering
  diffing, scoring, rule evaluation, and the CLI surface (markdown/json/
  sarif outputs, baseline lifecycle, hook install/uninstall, exit codes).

**Quality gates** (`source .venv/bin/activate`):

```
ruff check .          # clean
mypy --strict codegraph  # 42 files, no issues
pytest -q             # 130 passed
```
