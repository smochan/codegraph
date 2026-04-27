# codegraph

[![CI](https://github.com/smochan/codegraph/actions/workflows/ci.yml/badge.svg)](https://github.com/smochan/codegraph/actions/workflows/ci.yml)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Status](https://img.shields.io/badge/status-0.1.0--pre-yellow.svg)](https://github.com/smochan/codegraph)

> Pick a function. See exactly what calls it and what it calls. Drill in by expanding any node, fold back when you're done. External library calls stop at the boundary — your code stays in focus.

`codegraph` parses your repository with tree-sitter, stores a queryable graph of files /
classes / functions / imports / calls / inheritance / tests in a single SQLite file, and
exposes it through a CLI, a web dashboard with a 3D focus-mode flow tracer, and an
MCP server — so you and your AI assistant always have an accurate, lightweight map of
your codebase, no daemon required.

**Status:** 0.1.0 — pre-release / in-progress. Public PyPI publish is intentionally held
until the launch sprint completes (see [Roadmap](#roadmap)). For now, install from source.

> _(Dashboard screenshots coming with v0.1.1.)_

---

## What it does

### Parsing & graph

- **Build a code graph** for Python and TypeScript / JavaScript repositories via
  tree-sitter, at function / method / class granularity.
- **Single SQLite store** — no daemon, no database server, no network. The graph
  lives in `.codegraph/graph.db`, alongside the repo.
- **Cross-file resolution** with five categories of resolver fixes shipped in 0.1.0:
  per-name imports (`from x import a, b, c` emits 3 edges), Python relative imports,
  same-file constructor calls, decorator-call edges, class-annotation `self.X.Y`
  chains, and fresh-instance method calls.
- **DF0 — function signatures + per-call-site arguments** captured at parse time
  (text-only, no type inference). Powers signature tooltips and edge-arg labels in
  the 3D view.

### Analysis

- **Dead code with decorator-aware entry-point detection** — recognizes 24 framework
  decorators across Typer, FastAPI, Click, Celery, pytest, MCP, Flask, Django, and
  SQLAlchemy, so framework-registered handlers are never flagged as unused.
- **Call / import cycles**, reported with full **qualnames** (not opaque hashes) so
  you can actually discuss them.
- **Hotspots, untested functions, and aggregate metrics**.
- **DF1.5 — role classification** that tags functions and classes as
  `HANDLER` / `SERVICE` / `COMPONENT` / `REPO` based on framework patterns. Currently
  HTTP-framework-aware (FastAPI, Flask, Express, NestJS); Typer-CLI symbols are not
  classified as `HANDLER` yet — see [What it does NOT do yet](#what-it-does-not-do-yet).

### 3D focus-mode dashboard

- **Pick any function** from a role-grouped, searchable picker
  (`HANDLER` / `SERVICE` / `COMPONENT` / `REPO` sections, plus modules/classes/methods).
- **Trace ancestors and descendants** through the call graph; expand or collapse
  any node inline without losing your bearings.
- **Always-on node labels** plus an always-visible color/role legend.
- **Hover signature tooltips** show parameters and return-type annotations from DF0.
- **Edge labels** show the actual argument text (and kwargs) at each call site.
- **External calls render as terminal leaves** — they don't pull you out of your code.

### MCP server

- `codegraph mcp serve` — stdio-transport MCP server for Claude Code or any MCP client.
- 10 curated tools: `find_symbol` (with role filter), `callers`, `callees`
  (both surfacing args + role), `blast_radius`, `subgraph`, `dead_code`, `cycles`,
  `untested`, `hotspots`, `metrics`.
- Returns small, focused subgraphs — avoids flooding context windows.

### CLI

- `build`, `analyze`, `query`, `baseline`, `hook`, `mcp`, `serve`, `init`, `viz`,
  `explore`, `review`, `status`.

---

## What it does NOT do (yet)

Honest scope. These are on the roadmap, not in 0.1.0.

- **Type inference** (Mypy / Pyright integration) — DF0 captures *text* of params
  and call arguments, not flowed values or inferred types. v0.3+.
- **Cross-stack tracing** — frontend component → API endpoint → DB column,
  rendered as one continuous path. The v0.2 wedge (DF1–DF4 in
  [`.planning/PLAN_DATAFLOW.md`](.planning/PLAN_DATAFLOW.md)).
- **Argument-level data flow through a call chain** — DF0 captures arguments at
  each call site, but does not yet trace where a value flows. v0.2.
- **Per-language resolver parity** — Python ships the full set of resolver fixes
  in 0.1.0. The TypeScript R2 patterns (path aliases, fresh-instance binding,
  decorator-call edges) are deferred to v0.1.2.
- **Typer CLI symbols are not tagged `HANDLER`** — DF1.5 only classifies HTTP
  framework decorators today. CLI-handler classification is a v0.1.x follow-up.
- **Always-on sprite labels via `three-spritetext`** — labels currently render as
  always-on HTML overlays (library-native hover plus always-visible name labels).
  A separate worktree is shipping sprite-text labels concurrently; this README
  reflects what is visible in the 3D view today, not the in-flight branch.

---

## Honest engineering, on its own code

We pointed `codegraph` at its own source as the test case.

- Dead-code findings on the self-graph went from **451 to 4** as we fixed the
  resolver. The remaining 4 are intentional public-API surfaces or genuinely
  unwired helpers, documented in code:
  `analysis.roles._propagate_class_role_to_members`,
  `graph.store_sqlite.SQLiteGraphStore.upsert_node`,
  `graph.store_sqlite.SQLiteGraphStore.vacuum`, and
  `mcp_server.server._register.decorator`.
- We fixed **5+ categories** of resolver bugs along the way (per-name imports,
  relative imports, same-file constructor calls, nested-function call attribution,
  decorator-call edges, class-annotation `self.X.Y` chains, and fresh-instance
  method calls).
- The test suite is **273 passing Python tests** plus **55 Node tests** across
  `tests/test_graph3d_focus.js`, `tests/test_graph3d_transform.js`, and
  `tests/test_app_esc.js`.
- Cycles are now reported with qualnames, so we could actually triage them.
  Three are present today: a deliberate UI redraw loop in the dashboard, a
  parser self-recursion via `_visit_nested_defs` (intentional traversal), and an
  MCP `_serve ↔ run` static-resolver false positive — all documented in
  [`.planning/CYCLES_FOUND.md`](.planning/CYCLES_FOUND.md).

Numbers on the self-graph at HEAD: **2259 nodes, 4963 edges** (CALLS=3495,
DEFINED_IN=814, IMPORTS=634, INHERITS=20).

---

## Where it fits

Other code-graph tools each solve a slice. `codegraph`'s wedge: **external calls
stop at the boundary, decorator-aware analysis means framework handlers don't
show up as dead code, role classification (HANDLER/SERVICE/COMPONENT/REPO) is a
first-class output, and DF0 captures argument-level call-site text** so AI
assistants can reason about flow rather than just structure.

| | codegraph | GitNexus | code-review-graph | better-code-review-graph | JudiniLabs / mcp-code-graph | RepoMapper | Graphify |
|---|:-:|:-:|:-:|:-:|:-:|:-:|:-:|
| Local-first, single SQLite, no daemon | ✅ | ✅ | ✅ | ✅ | partial | ✅ | varies |
| MCP-native | ✅ | partial | ❌ | ❌ | ✅ | ❌ | ❌ |
| External calls stop at boundary | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| Decorator-aware dead code (24 frameworks) | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| Role classification (HANDLER/SERVICE/...) | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| Argument-level data flow text capture (DF0) | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| 3D focus-mode flow tracer | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ | partial |
| Cycles reported with qualnames | ✅ | partial | ❌ | ❌ | ❌ | ❌ | ❌ |
| Open source, MIT | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | varies |

Languages today: **Python and TypeScript / JavaScript / TSX / JSX**. Go, Java,
Rust, C#, Ruby, PHP are roadmap items — adding each is a single-file tree-sitter
mapping. Until then you'll get module-level nodes but not function-level
granularity.

---

## Prior art and related projects

`codegraph` was built independently. It is **not a fork** of, and does not
descend from, any other code-graph project. Other projects in the local
code-graph / MCP-for-AI space worth knowing about:
[code-review-graph](https://github.com/tirth8205/code-review-graph) and its
fork [better-code-review-graph](https://github.com/n24q02m/better-code-review-graph)
(token-efficient review context with embeddings), GitNexus (visualisation polish,
broader graph), and JudiniLabs/mcp-code-graph. `codegraph`'s wedge is
decorator-aware dead-code detection, role classification, a 3D focus-mode flow
tracer, and (in v0.2) cross-stack data-flow tracing — not embedding-based
retrieval.

---

## How codegraph collects context (vs. the alternatives)

Most "AI for code" tooling sits in one of five camps. Each has a different
shape of strength and a different shape of blind-spot.

| Approach | Examples | Strength | Blind-spot |
|---|---|---|---|
| **Embedding retrieval** | Cursor, Cody, Continue, code-review-graph | Prose, comments, docstrings; language-agnostic | Structurally blind — name similarity ≠ "calls X" |
| **AST / tree-sitter graph** | **codegraph**, RepoGraph, GitNexus | Exact call/import edges; deterministic | Misses prose; one parser per language |
| **LSP / compiler-grade** | Sourcegraph SCIP | Real types, scope-aware | Slow; one server per language; complex |
| **Repo map / outline** | Aider `repomap.py` | Lightweight orientation | No edge traversal — model still has to ask for files |
| **Grep + file-tree** | Bare Claude Code, Codex without MCP | Trivial | No semantics; model wastes turns guessing |

**Where codegraph wins:** anything involving call relationships. *"Trace this
function's args through the system." "Show HANDLERs without test coverage."
"Did this refactor break a caller?" "What's the blast radius?"* The graph
answers these with structural certainty, not similarity scores. DF0 (per-call-site
args) and DF1.5 (HANDLER/SERVICE/COMPONENT/REPO classification) are differentiators
inside the graph-based camp — RepoGraph and GitNexus don't have either.

**Where codegraph loses:** *"Find the function that handles refunds"* if the
word `refunds` only appears in a docstring. *"Why is this written this way?"*
We don't index prose — embedding tools handle that better.

**Where they're complementary:** the right architecture for a real product is
**graph + embeddings in the same MCP loop**, not one or the other. Cursor uses
both internally. The roadmap below puts an open-source embedding layer in v0.3
so codegraph can offer the same hybrid retrieval, locally, with no API keys.

---

## Quickstart

```bash
git clone https://github.com/smochan/codegraph.git
cd codegraph
python -m venv .venv && source .venv/bin/activate
pip install -e .

codegraph init                     # interactive setup (languages, ignore globs, MCP config)
codegraph build                    # parse repo → SQLite graph
codegraph analyze                  # dead code · cycles · hotspots · untested · metrics
codegraph serve                    # web dashboard at http://127.0.0.1:8765
codegraph review                   # graph-diff PR review with risk score
```

> PyPI package coming soon. Until then, install from source as above.

---

## Commands

| Command | Description |
|---------|-------------|
| `codegraph init` | Interactive setup: detect languages, configure ignore globs, optionally register MCP. |
| `codegraph build` | Walk the repo, parse with tree-sitter, write / update `graph.db`. |
| `codegraph status` | Show graph freshness, last build, and drift indicators. |
| `codegraph analyze` | Whole-project audit: dead code, cycles, untested, hotspots, metrics. |
| `codegraph viz` | Render the graph as Mermaid, interactive HTML, or SVG. |
| `codegraph explore` | Generate static subgraph explorer pages. |
| `codegraph serve` | Launch the web dashboard (default port 8765). |
| `codegraph review` | Graph-diff current branch vs baseline; output risk report. |
| `codegraph query callers <sym>` | Reverse-BFS: who calls a symbol? |
| `codegraph query subgraph <sym>` | Induced subgraph around a symbol. |
| `codegraph query deadcode` | List unreferenced functions/classes. |
| `codegraph query untested` | List functions with no incoming calls from a test module. |
| `codegraph query cycles` | Show import / call strongly-connected components. |
| `codegraph baseline save` | Snapshot the current graph as a named baseline. |
| `codegraph baseline status` | Compare current graph to the saved baseline. |
| `codegraph baseline push` | Push baseline to remote store (S3 optional). |
| `codegraph hook install` | Install a pre-push git hook that runs `codegraph review`. |
| `codegraph hook uninstall` | Remove the pre-push git hook. |
| `codegraph mcp serve` | Start the MCP server (stdio transport) for Claude Code. |

---

## Use with MCP-compatible AI clients

`codegraph` ships an MCP server (`codegraph mcp serve`) that exposes the
graph to any client supporting the [Model Context Protocol](https://modelcontextprotocol.io/).
The server config is identical across clients — only the file location differs.

### Claude Code

Add to `~/.claude.json` (or register with `claude mcp add`):

```json
{
  "mcpServers": {
    "codegraph": {
      "command": "codegraph",
      "args": ["mcp", "serve", "--db", ".codegraph/graph.db"]
    }
  }
}
```

### Cursor

Add to `~/.cursor/mcp.json` (or per-workspace `.cursor/mcp.json`):

```json
{
  "mcpServers": {
    "codegraph": {
      "command": "codegraph",
      "args": ["mcp", "serve", "--db", ".codegraph/graph.db"]
    }
  }
}
```

### Codex CLI

Codex reads MCP config from `~/.codex/config.toml`:

```toml
[mcp_servers.codegraph]
command = "codegraph"
args = ["mcp", "serve", "--db", ".codegraph/graph.db"]
```

### VS Code (Continue, Cline, or any MCP extension)

Most VS Code AI extensions accept the same JSON shape under their own
settings key. Continue uses `~/.continue/config.json` → `mcpServers`;
Cline uses the workspace MCP settings. Point them at the `codegraph`
binary the same way.

### Once connected

Inside any of these clients, you can ask things like:

> *"Which functions have the highest blast radius in the auth module?"*
> *"Show me everything that calls `UserService.login`, and surface the args at each call site."*
> *"List the HANDLER nodes — which routes have no test coverage?"*
> *"Are there any import cycles in this PR?"*

The available tools are: `find_symbol` (now with a `role` filter),
`callers`, `callees`, `blast_radius`, `subgraph`, `dead_code`, `cycles`,
`untested`, `hotspots`, `metrics`.

---

## Development

New to the repo? Read [`docs/GETTING_STARTED.md`](docs/GETTING_STARTED.md)
for the full walkthrough.

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

ruff check .                        # lint
mypy --strict codegraph             # type-check
pytest -q                           # 273 Python tests
node --test tests/*.js              # 55 JS tests
```

---

## Acknowledgements

`codegraph` stands on:
[tree-sitter](https://tree-sitter.github.io/) (parsing),
[vasturiano/3d-force-graph](https://github.com/vasturiano/3d-force-graph)
(3D rendering), [networkx](https://networkx.org/) (graph algorithms),
[pydantic](https://docs.pydantic.dev/) (typed schema),
[typer](https://typer.tiangolo.com/) (CLI),
[rich](https://rich.readthedocs.io/) (console output), and the
[Model Context Protocol Python SDK](https://modelcontextprotocol.io/).

---

## Roadmap

See [`.planning/MASTER_PLAN.md`](.planning/MASTER_PLAN.md) and
[`.planning/PLAN_DATAFLOW.md`](.planning/PLAN_DATAFLOW.md) for detail.

- **v0.1.1** — always-on sprite-text labels in 3D view (in flight on a separate
  worktree); dashboard screenshots; small UX follow-ups.
- **v0.1.2** — TypeScript R2 resolver patterns (path aliases, fresh-instance
  binding, decorator-call edges); CLI `HANDLER` classification for Typer/Click.
- **v0.2** — cross-stack data-flow tracing: DF1 (FastAPI ROUTE + SQLAlchemy
  READS_FROM/WRITES_TO), DF2 (React FETCH_CALL), DF3 (URL stitcher with
  confidence scores), DF4 (`dataflow trace` CLI + MCP tool + dashboard Sankey).
  See [`.planning/PLAN_DATAFLOW.md`](.planning/PLAN_DATAFLOW.md) and
  [`.planning/PLAN_V0_2_PARAMETERS.md`](.planning/PLAN_V0_2_PARAMETERS.md).
- **v0.3 — local embedding layer.** Add `codegraph embed` (chunks + open-weight
  model → on-disk vector store; default candidates: `CodeRankEmbed` (Apache 2.0,
  ~140 MB, code-tuned) or `nomic-embed-v2`, with `LanceDB` as the store).
  New MCP tools: `semantic_search(query, k)` and `hybrid_search(query, role=…, k)`
  — embedding similarity reranked by graph distance. End-to-end install stays
  pure-pip, no API keys, no Docker. This closes the prose / semantic gap from
  the comparison above without giving up structural correctness.
- **v0.3+** — Mypy / Pyright type inference integration; more languages
  (Rust, Go, C# via tree-sitter); benchmark publication
  ([`.planning/RESEARCH_BENCHMARKS.md`](.planning/RESEARCH_BENCHMARKS.md)).
- **Benchmark work (deferred until 0.1.0 lands publicly)** —
  [`.planning/RESEARCH_BENCHMARKS.md`](.planning/RESEARCH_BENCHMARKS.md) lays
  out a CrossCodeEval pre-flight (~$50, hours) and a SWE-bench Lite +
  Agentless run (~$400–900, 24–48h) targeting a +2 to +4 absolute resolve-rate
  gain over the published RepoGraph result. Held until the public release
  ships so the benchmark numbers ship attached to a real package.

---

## License

[MIT](LICENSE) © mochan
