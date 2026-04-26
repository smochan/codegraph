# codegraph

[![CI](https://github.com/smochan/codegraph/actions/workflows/ci.yml/badge.svg)](https://github.com/smochan/codegraph/actions/workflows/ci.yml)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![PyPI](https://img.shields.io/pypi/v/codegraph-py.svg)](https://pypi.org/project/codegraph-py/)
[![Status](https://img.shields.io/badge/status-0.1.0-brightgreen.svg)](https://github.com/smochan/codegraph/releases)

> Pick a function. See exactly what calls it and what it calls. Drill in by expanding any node, fold back when you're done. External library calls stop at the boundary — your code stays in focus.

`codegraph` parses your repository with tree-sitter, stores a queryable graph of files /
classes / functions / imports / calls / inheritance / tests in a single SQLite file, and
exposes it through a CLI, a web dashboard with a 3D focus-mode flow tracer, and an
MCP server — so you and your AI assistant always have an accurate, lightweight map of
your codebase, no daemon required.

**Status:** 0.1.0 — ready for PyPI.

![dashboard](docs/images/dashboard.png)

---

## What it does

- **Build a code graph** for Python and TypeScript / JavaScript repositories via
  tree-sitter, at function / method / class granularity.
- **Analyze**:
  - Dead code with **decorator-aware** entry-point detection — recognizes 24
    framework decorators across Typer, FastAPI, Click, Celery, pytest, MCP, and more,
    so framework-registered handlers are never flagged as unused.
  - Call / import cycles, reported with full **qualnames** (not opaque hashes) so
    you can actually discuss them.
  - Hotspots, untested functions, and aggregate metrics.
- **Web dashboard** — HLD layered view, hotspots, treemap, sankey, and a
  **3D focus-mode flow tracer**: pick any function, expand neighbors inline,
  fold them back when you're done. External calls render at the boundary as
  terminal leaves — they don't pull you out of your code.
- **MCP server** — 10 curated tools for Claude Code or any MCP client:
  `find_symbol`, `callers`, `callees`, `blast_radius`, `subgraph`, `dead_code`,
  `cycles`, `untested`, `hotspots`, `metrics`.
- **CLI** — `build`, `analyze`, `query`, `baseline`, `hook`, `mcp`, `serve`,
  plus `init`, `viz`, `explore`, `review`, `status`.
- **Single SQLite store** — no daemon, no database server, no network. The graph
  lives in `.codegraph/graph.db`, alongside the repo.

---

## What it does NOT do (yet)

Honest scope. These are on the roadmap, not in 0.1.0.

- **Argument-level data flow** — which argument flows where through a call chain.
  Targeted for v0.2.
- **Service / component classification** — labelling nodes as
  `HANDLER` / `SERVICE` / `COMPONENT` / `REPO` based on framework patterns.
  Targeted for v0.2.
- **Cross-stack tracing** — frontend component → API endpoint → DB column,
  rendered as one continuous path. The v0.2 wedge.
- **Type inference** (Mypy / Pyright integration) — v0.3 or later.
- **Per-language resolver parity** — Python ships the full set of fixes in 0.1.0
  (per-name imports, relative imports, same-file constructor calls,
  nested-function call attribution, decorator-call edges, class-annotation
  `self.X.Y` chains, fresh-instance method calls). The TypeScript R2 patterns
  are deferred to v0.1.2.

---

## Honest engineering, on its own code

We pointed `codegraph` at its own source as the test case.

- Dead-code findings on the self-graph went from **451 to 3** as we fixed the
  resolver; the remaining 3 are intentional public-API surfaces, documented in
  code.
- We fixed **5 categories** of resolver bugs along the way (per-name imports,
  relative imports, same-file constructor calls, nested-function call
  attribution, decorator-call edges, class-annotation `self.X.Y` chains,
  fresh-instance method calls).
- The test suite grew from **147 to 202 passing** tests across Python and JS.
- Cycles are now reported with qualnames, so we could actually triage them.
  Three were found; two are accepted (one intentional UI redraw loop, one
  static-resolver false positive against the MCP `Server.run` method); the
  third is tracked as a v0.1.1 resolver follow-up.

---

## Where it fits

Other code-graph tools each solve a slice. `codegraph` isn't competing on
"biggest graph" — the wedge is **your code's flow stays in focus**: external
library calls stop at the boundary, and decorator-aware analysis means
framework handlers don't show up as dead code.

| | codegraph | Sourcegraph | GitHub Code Search | LSP / IDE | grep / ripgrep | tree-sitter alone |
|---|---|---|---|---|---|---|
| Multi-language graph (calls / inheritance / imports) | ✅ | ✅ | partial | per-language | ❌ | DIY |
| Single-binary, runs locally | ✅ | ❌ heavyweight | ❌ cloud | ✅ | ✅ | ✅ |
| Built-in PR risk review (diff + rules + SARIF) | ✅ | partial / paid | ❌ | ❌ | ❌ | ❌ |
| MCP server for Claude / AI agents | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ |
| Web dashboard with 3D focus-mode flow tracer | ✅ | partial | ❌ | ❌ | ❌ | ❌ |
| Decorator-aware dead-code (Typer / FastAPI / Click / Celery / pytest / MCP) | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ |
| Cycles / hotspots / untested out-of-the-box | ✅ | ❌ | ❌ | partial | ❌ | ❌ |
| Zero-config: one SQLite file, no daemon | ✅ | ❌ | n/a | ✅ | ✅ | ✅ |
| Open source, MIT, free for any size repo | ✅ | partial (OSS core) | n/a | mixed | ✅ | ✅ |

Languages today: **Python and TypeScript / JavaScript**. Go, Java, Rust, C#,
Ruby, PHP are roadmap items — adding each is a single-file tree-sitter mapping.
Until then you'll get module-level nodes but not function-level granularity.

---

## Quickstart

```bash
pip install codegraph-py
codegraph init                     # interactive setup (languages, ignore globs, MCP config)
codegraph build                    # parse repo → SQLite graph
codegraph analyze                  # dead code · cycles · hotspots · untested · metrics
codegraph serve                    # web dashboard at http://127.0.0.1:8765
codegraph review                   # graph-diff PR review with risk score
```

> `codegraph-py` is the PyPI distribution name. The CLI command is `codegraph`.

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

## Use with Claude Code

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

Then, inside a Claude Code conversation, you can ask:

> *"Which functions have the highest blast radius in the auth module?"*
> *"Show me everything that calls `UserService.login`."*
> *"Are there any import cycles in this PR?"*

---

## Development

New to the repo? Read [`docs/GETTING_STARTED.md`](docs/GETTING_STARTED.md)
for the full walkthrough.

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

ruff check .                        # lint
mypy --strict codegraph             # type-check
pytest -q                           # tests (202 passing across Python + JS)
```

---

## Roadmap

See [`docs/plan.md`](docs/plan.md) for the full phased roadmap. Highlights:

- **v0.1.1** — TS R2 resolver patterns; small UX follow-ups.
- **v0.2** — argument-level data flow; service / component classification;
  cross-stack tracing (frontend → API → DB).
- **v0.3+** — type inference integration; more languages.

---

## License

[MIT](LICENSE) © mochan
