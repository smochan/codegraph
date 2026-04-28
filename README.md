# codegraph

[![CI](https://github.com/smochan/codegraph/actions/workflows/ci.yml/badge.svg)](https://github.com/smochan/codegraph/actions/workflows/ci.yml)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Status](https://img.shields.io/badge/status-0.1.0--pre-yellow.svg)](https://github.com/smochan/codegraph)

> Pick a function. See exactly what calls it and what it calls. Drill in by expanding any node, fold back when you're done. External library calls stop at the boundary — your code stays in focus.

`codegraph` parses your repository with tree-sitter, stores a queryable graph of files /
classes / functions / imports / calls / inheritance / tests in a single SQLite file, and
exposes it through a CLI, a web dashboard with a 3D focus-mode flow tracer, an
**Architecture view with a Learn Mode request-lifecycle modal**, and an MCP server — so
you and your AI assistant always have an accurate, lightweight map of your codebase,
no daemon required.

**Highlights shipped on `main` (since the last README refresh):**

- **Cross-stack data-flow tracing — DF1 → DF4 — is now in the box.** HTTP routes
  (DF1), SQLAlchemy reads/writes (DF1), frontend `FETCH_CALL` edges (DF2), URL
  stitching (DF3), and an end-to-end `codegraph dataflow trace` walker (DF4) —
  available as a CLI subcommand and as the `dataflow_trace` MCP tool.
- **Architecture view + Learn Mode lifecycle modal.** The web dashboard now
  ships a project-aware Architecture view (handlers, services, repositories,
  external infrastructure components) and a Learn Mode modal that animates the
  full request lifecycle — TCP handshake → TLS → HTTP → data layer → response —
  for any handler in the repo.
- **15 MCP tools** (was 10), including the v0.3 embedding tools and the DF1 /
  DF2 / DF4 trace tools.

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

#### Cross-stack tracing (DF1)

- **`ROUTE` edges** from FastAPI / Flask / aiohttp handlers to a synthetic
  `route::METHOD::/path` node. `@app.get("/x")`, `@router.post("/y")`, and Flask's
  `@app.route("/z", methods=["POST", "PUT"])` are all detected; the Flask form
  expands to one edge per method.
- **`READS_FROM` / `WRITES_TO` edges** for SQLAlchemy data-access — `session.query(Model)`,
  `Model.query.filter(...)`, `db.session.query(Model)`, `session.add(Model(...))`, and
  `session.execute(select|insert|update|delete(Model))`. Edges resolve to the in-repo
  `CLASS` node for the model; unresolved targets are dropped (no `unresolved::*`
  noise in the graph).
- **HLD payload** (`build_hld`) surfaces these as the `routes` and `sql_io` arrays
  alongside the existing layered diagram, so dashboards and MCP clients can answer
  "which handler writes to `User`?" in one query.
- **MCP tool** `dataflow_routes` returns the list of `{handler_qn, method, path, framework}`
  records for any connected client.

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
- 15 curated tools: `find_symbol` (with role filter), `callers`, `callees`
  (both surfacing args + role), `blast_radius`, `subgraph`, `dead_code`, `cycles`,
  `untested`, `hotspots`, `metrics`, `semantic_search`, `hybrid_search`
  (v0.3 embeddings), `dataflow_routes` (DF1 HTTP routes), `dataflow_fetches`
  (DF2 frontend fetches), and `dataflow_trace` (DF4 end-to-end trace
  frontend → handler → service → repo → DB).
- Returns small, focused subgraphs — avoids flooding context windows.

### CLI

- `build`, `analyze`, `query`, `baseline`, `hook`, `mcp`, `serve`, `init`, `viz`,
  `explore`, `review`, `status`.

### Architecture view + Learn Mode lifecycle modal

- **Architecture dashboard tab.** Detects infrastructure components in the
  repo (web framework, ORM / database, cache, message queue, external HTTP
  clients) and groups them alongside the role-classified application layer
  (HANDLER / SERVICE / REPO).
- **Learn Mode modal.** Click a handler and walk through the full request
  lifecycle as an animated sequence diagram or pipeline view: TCP handshake
  → TLS → HTTP request → data layer → response. Every phase is a teaching
  moment with collapsible explanatory copy.
- **Pipeline + sequence diagrams.** Both modes share state and persist to
  `localStorage` — open the modal next time and you land in the view you
  used last.

### Cross-stack tracing (DF3 → DF4)

- **DF3 — URL stitcher (`match_route`).** Stitches frontend `FETCH_CALL`
  URLs to backend `ROUTE` handlers with placeholder normalisation
  (`/users/{id}` ↔ `${id}` ↔ `:id` ↔ numeric segments) and a body-key
  overlap bonus when both sides agree on the request shape.
- **DF4 — `codegraph dataflow trace`.** Walks the call graph + DF1 / DF2
  cross-layer edges and emits an ordered `DataFlow` of hops from
  frontend `FETCH_CALL` through the handler, service, and repository
  layers to the SQL read / write target. Available as a CLI subcommand
  (`codegraph dataflow trace "GET /api/users/{id}"`) and as the
  `dataflow_trace` MCP tool.

### Cross-stack tracing (DF2)

- **`FETCH_CALL` extraction** — TypeScript / TSX / JavaScript parser detects
  HTTP call sites and emits a `FETCH_CALL` edge from the enclosing function or
  method to a synthetic URL node. Recognised libraries:
  - `fetch(url, init?)` — global fetch (method/body inferred from the init
    object literal, including `body: JSON.stringify({...})`)
  - `axios.get|post|put|delete|patch(url, body?)` and `axios({ method, url, data })`
  - `useSWR(url, fetcher)` — treated as `GET`
  - `useQuery({ queryKey, queryFn })` — best-effort when `queryFn` is a simple
    fetch / axios call
  - `apiClient.get|post|put|delete(url)` — generic api-client heuristic
- **Body-key capture** — top-level keys of the request body object literal
  (or the object passed to `JSON.stringify`) are surfaced as `body_keys`
  metadata, which DF3 will use to disambiguate same-route handlers by
  argument shape.
- **URL handling** — string literals are captured verbatim; template literals
  preserve their `${...}` placeholders; identifier-only URLs flag
  `url_kind="dynamic"` so the stitcher can skip path normalisation.
- **HLD payload** — `serialize_fetch_edges` exposes the per-call-site list as
  `payload.fetches` for DF3 / DF4 consumers.

---

## What it does NOT do (yet)

Honest scope. These are on the roadmap, not on `main` yet.

- **Argument-flow propagation across hops.** DF0 captures the *text* of each
  call-site argument, and DF4 emits an ordered list of hops, but the value
  identity of a single argument (e.g. `user_id`) is not yet traced from the
  fetch body → route param → service arg → DB query. Planned for v0.3 (see
  [`.planning/PLAN_V0_3_UNIFIED_TRACE.md`](.planning/PLAN_V0_3_UNIFIED_TRACE.md)).
- **Type inference** (Mypy / Pyright integration). DF0 is text-only. v0.3+.
- **Per-language resolver parity.** Python ships the full set of resolver fixes
  in 0.1.0. The TypeScript R2 patterns (path aliases, fresh-instance binding,
  decorator-call edges) are deferred to v0.1.2.
- **Typer CLI symbols are not tagged `HANDLER`.** DF1.5 only classifies HTTP
  framework decorators today. CLI-handler classification is a v0.1.x follow-up.

---

## Honest engineering, on its own code

We pointed `codegraph` at its own source as the test case.

- Dead-code findings on the self-graph went from **451 → 24+ → 15 → 0** as
  we fixed the resolver, added decorator-aware entry-point detection, and
  added a `# pragma: codegraph-public-api` exemption for intentional library
  surface. Today the self-graph reports **0 dead-code findings** —
  honestly, with the only "skips" being decorators, Protocols, and fixture
  paths.
- We fixed **6+ categories** of resolver bugs along the way (per-name imports,
  relative imports, same-file constructor calls, nested-function call attribution,
  decorator-call edges, class-annotation `self.X.Y` chains, fresh-instance
  method calls, and conditional `self.X` assignments via R3).
- The test suite is **537 Python + 100 Node = 637 tests passing**, all
  green. DF0 → DF4, the Architecture view + Learn Mode lifecycle modal,
  argument-flow propagation, the embeddings layer, and the PR-review CI
  all have regression coverage.
- Cycles are now reported with qualnames, so we could actually triage them.
  Three are present today: a deliberate UI redraw loop in the dashboard
  (`hldRenderNav → jumpToQualname → drawFocusGraph`), a parser self-recursion
  via `_visit_nested_defs` (intentional traversal), and an MCP `_serve ↔ run`
  static-resolver false positive — all documented in
  [`.planning/CYCLES_FOUND.md`](.planning/CYCLES_FOUND.md).

Numbers on the self-graph at HEAD: **3,320 nodes, 7,557 edges**
(CALLS=5,245, DEFINED_IN=1,357, IMPORTS=886, INHERITS=28, ROUTE=12,
FETCH_CALL=27, READS_FROM=1, WRITES_TO=1).

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

### Try the cross-stack demo

A small FastAPI + SQLAlchemy + React fixture lives in
[`examples/cross-stack-demo/`](examples/cross-stack-demo/). Run codegraph
against it to see DF1 (routes), DF2 (fetches), DF1.5 (roles), and DF3/DF4
(end-to-end trace) all light up:

```bash
codegraph build --no-incremental --root examples/cross-stack-demo
codegraph dataflow trace "GET /api/users/{user_id}"
```

See the demo's [README](examples/cross-stack-demo/README.md) for expected
output and what to look for.

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
`untested`, `hotspots`, `metrics`, v0.3's `semantic_search` and
`hybrid_search`, plus the cross-stack tracing tools `dataflow_routes`,
`dataflow_fetches`, and `dataflow_trace`.

### Hybrid retrieval (v0.3)

Structural graphs are great at "who calls this" and "what depends on this",
but they don't answer "show me code that handles password reset" — that's a
prose / semantics question. v0.3 adds an opt-in local embedding layer so
codegraph covers both retrieval styles.

```bash
pip install -e ".[embed]"   # pulls sentence-transformers + lancedb
codegraph build              # graph first
codegraph embed              # chunks + embeds + writes .codegraph/embeddings.lance
```

The default model is [`nomic-ai/CodeRankEmbed`](https://huggingface.co/nomic-ai/CodeRankEmbed)
(Apache 2.0, ~140 MB, 768-dim, code-tuned). Override with `--model` for any
HuggingFace sentence-transformer. Vectors land in `.codegraph/embeddings.lance`
alongside the graph DB.

Two new MCP tools come online once the index exists:

- **`semantic_search(query, k=5)`** — pure cosine similarity over the index.
  Returns `[{qualname, file, line, kind, role, score, text_snippet}]`.
- **`hybrid_search(query, k=5, role=None, focus_qualname=None)`** — same
  ranking, optionally filtered by role (`HANDLER` / `SERVICE` / `COMPONENT` /
  `REPO`) and reranked by graph distance from `focus_qualname` using
  `final_score = 0.6 · cosine + 0.4 · 1/(1+hops)`.

Everything runs locally — no API keys, no Docker. If the index is missing,
both tools return `{"error": "no embedding index — run `codegraph embed` first"}`.

---

## Development

New to the repo? Read [`docs/GETTING_STARTED.md`](docs/GETTING_STARTED.md)
for the full walkthrough.

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

ruff check .                        # lint
mypy --strict codegraph             # type-check
pytest -q                           # 484 Python tests + 3 skipped (487 total)
node --test tests/*.js              # JS unit tests (graph3d focus, transform, ESC handling)
```

---

## PR review CI (dogfood)

`codegraph` ships its own PR-review workflow as a template. Once activated,
every PR opened against `main` runs codegraph against itself, posts the diff
as a sticky PR comment, and fails the check on high-severity findings.

The workflow lives at
[`.github/ci-templates/pr-review.workflow.yml`](.github/ci-templates/pr-review.workflow.yml)
(outside `.github/workflows/` so the repo can be cloned and pushed-to with a
token that lacks the `workflow` OAuth scope). Activate with:

```bash
gh auth refresh -h github.com -s workflow
cp .github/ci-templates/pr-review.workflow.yml .github/workflows/pr-review.yml
git add .github/workflows/pr-review.yml
git commit -m "ci: activate codegraph PR review"
git push
```

Once active, the workflow:

1. Builds a graph from `origin/main` and saves it as a baseline.
2. Builds a graph from the PR head.
3. Runs `codegraph review --format markdown --fail-on high` against the diff.
4. Posts the result as a sticky PR comment (replaced on each push, no spam).
5. Fails the check if any high-or-critical findings appear.

**Local dry-run** before opening a PR:

```bash
git fetch origin main
./scripts/test-pr-review-locally.sh
# writes review.md + comment.md, exits non-zero if findings exceed --fail-on high
```

First-PR graceful path: if no baseline can be saved from `main` (brand-new
repo, empty default branch), the workflow posts a friendly "first-time
review" comment and passes — codegraph review activates from the next PR.

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

**Already shipped on `main`:**

- v0.1.1 — always-on labels in the 3D view, dashboard polish.
- v0.2 — DF1 (FastAPI / Flask `ROUTE` + SQLAlchemy `READS_FROM` / `WRITES_TO`),
  DF1.5 (role classification), DF2 (React `FETCH_CALL`), DF3 (URL stitcher),
  DF4 (`codegraph dataflow trace` CLI + `dataflow_trace` MCP tool).
- v0.3 embeddings — `codegraph embed` + `semantic_search` + `hybrid_search`.
- Architecture view + Learn Mode lifecycle modal (PR #15).
- PR-review CI (`codegraph review` on every PR, posts sticky comment / step
  summary on fork PRs).

**Pending:**

- **v0.1.2** — TypeScript R2 resolver patterns (path aliases, fresh-instance
  binding, decorator-call edges); CLI `HANDLER` classification for Typer / Click.
- **v0.3 unified trace** — wire DF4's `DataFlow` output into the Architecture
  view's Learn Mode Phase 4 (project-specific data layer) so clicking a handler
  shows the *real* chain (handler → service → repo → SQL target) inside the
  lifecycle modal. Stretch: argument-flow propagation, where `user_id` is
  highlighted as it travels from fetch body → route param → service arg → DB
  query. See [`.planning/PLAN_V0_3_UNIFIED_TRACE.md`](.planning/PLAN_V0_3_UNIFIED_TRACE.md).
- **Type inference** — Mypy / Pyright integration. v0.3+.
- **More languages** — Rust, Go, C# via tree-sitter. v0.4+.
- **Benchmark publication** —
  [`.planning/RESEARCH_BENCHMARKS.md`](.planning/RESEARCH_BENCHMARKS.md) lays
  out a CrossCodeEval pre-flight (~$50, hours) and a SWE-bench Lite +
  Agentless run (~$400–900, 24–48h) targeting a +2 to +4 absolute resolve-rate
  gain over the published RepoGraph result. Held until PyPI publish so the
  numbers ship attached to a real package.
- **PyPI publish + LinkedIn launch** — held until the v0.3 unified trace
  lands so the launch post can show the full end-to-end demo, not the
  fragmented one we have today.

---

## Project status & launch

The 0.1.0 launch is **functionally complete** — all code, tests, dashboards,
and CI are shipped on `main`. Three manual steps remain (record demo →
PyPI publish → LinkedIn launch). See:

- [`LAUNCH_CHECKLIST.md`](LAUNCH_CHECKLIST.md) — sequenced launch steps with exact commands.
- [`docs/DEMO_SCRIPT.md`](docs/DEMO_SCRIPT.md) — storyboard for the launch video (45s landscape + 5s square loop).
- [`docs/GETTING_STARTED.md`](docs/GETTING_STARTED.md) — one-page guide for running codegraph against your own repo.
- [`.planning/SESSION_HANDOFF.md`](.planning/SESSION_HANDOFF.md) — the briefing doc for resuming work in a new session.

---

## Contributing

See [`CONTRIBUTING.md`](CONTRIBUTING.md) — covers local setup, what CI
checks (and how to run the same checks locally before pushing), commit /
PR conventions, and the merge process. Run
`./scripts/test-pr-review-locally.sh` before opening a PR to catch CI
failures one round-trip earlier.

---

## License

[MIT](LICENSE) © mochan
