# codegraph

[![CI](https://github.com/smochan/codegraph/actions/workflows/ci.yml/badge.svg)](https://github.com/smochan/codegraph/actions/workflows/ci.yml)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![PyPI](https://img.shields.io/pypi/v/codegraph-py.svg)](https://pypi.org/project/codegraph-py/)

> Language-agnostic code graph builder, analyzer, PR risk reviewer, and MCP server for Claude Code.

`codegraph` parses your repository with tree-sitter, stores a queryable graph of files / classes /
functions / imports / calls / inheritance / tests in a single SQLite file, and exposes it through a
polished CLI, a web dashboard, and a 10-tool MCP server — so you and your AI assistant always have
an accurate, lightweight map of your codebase, no daemon required.

<!-- Screenshots will be added once the dashboard is recorded. -->
![dashboard](docs/images/dashboard.png)

---

## Why codegraph?

Existing tools each solve a slice; codegraph stitches them together for the
AI-assisted workflow.

| | codegraph | Sourcegraph | GitHub Code Search | LSP / IDE | grep / ripgrep | tree-sitter alone |
|---|---|---|---|---|---|---|
| Multi-language graph (calls / inheritance / imports) | ✅ | ✅ | partial | per-language | ❌ | DIY |
| Single-binary, runs locally | ✅ | ❌ heavyweight | ❌ cloud | ✅ | ✅ | ✅ |
| Built-in PR risk review (diff + rules + SARIF) | ✅ | partial / paid | ❌ | ❌ | ❌ | ❌ |
| MCP server for Claude / AI agents | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ |
| Web dashboard with HLD + focus graph | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ |
| Dead code / cycles / hotspots out-of-the-box | ✅ | ❌ | ❌ | partial | ❌ | ❌ |
| Zero-config: one SQLite file, no daemon | ✅ | ❌ | n/a | ✅ | ✅ | ✅ |
| Open source, MIT, free for any size repo | ✅ | partial (OSS core) | n/a | mixed | ✅ | ✅ |

**Where codegraph fits:** between "I just want to grep the repo" and "let's run a
self-hosted Sourcegraph instance." It's the lightest tool that gives both
*humans* (dashboard, analysis) and *AI agents* (MCP) a real graph of the code,
not just text matches.

**Where it doesn't (yet):** only Python / TypeScript / JavaScript extractors
ship today. Go, Java, Rust, C#, Ruby, PHP are in the roadmap (Phase 2) — adding
each is a single-file tree-sitter mapping. Until then you'll get module-level
nodes but not function-level granularity for those languages.

---

## Quickstart

```bash
pip install codegraph-py           # install from PyPI (not yet published — see Install below)
codegraph init                     # interactive setup (languages, ignore globs, MCP config)
codegraph build                    # parse repo → SQLite graph
codegraph analyze                  # dead code · cycles · hotspots · untested · metrics
codegraph serve                    # open web dashboard at http://localhost:8000
codegraph review                   # graph-diff PR review with risk score
```

---

## Features

1. **Multi-language graph** — Python, TypeScript, and JavaScript today; pluggable tree-sitter
   extractors make adding any language a one-file change.
2. **Rich analysis** — dead code, import cycles, call hotspots, untested functions, blast-radius
   queries, and aggregate metrics — all in one command.
3. **PR review** — graph diff against a saved baseline, risk scoring, YAML rule packs, output in
   Markdown / JSON / SARIF, and an optional pre-push git hook.
4. **Web dashboard** — HLD navigator, animated focus graph, collapsible sidebar, light/dark themes;
   served locally with a single `codegraph serve`.
5. **MCP server** — 10 curated tools (`find_symbol`, `callers`, `callees`, `blast_radius`,
   `subgraph`, `dead_code`, `cycles`, `untested`, `hotspots`, `metrics`) for Claude Code or any
   MCP client.
6. **Single SQLite store** — no daemon, no database server, no network required. The entire graph
   lives in `.codegraph/graph.db`.
7. **Standalone CLI** — works fully offline, MIT licensed, zero telemetry.

---

## Install

```bash
pip install codegraph-py
```

> **Note:** `codegraph-py` is the PyPI distribution name. The CLI command is `codegraph`.
> The package is not yet published to PyPI — to try it today, install from source:
>
> ```bash
> git clone https://github.com/smochan/codegraph.git
> cd codegraph
> pip install -e .
> ```

---

## Commands

| Command | Description |
|---------|-------------|
| `codegraph init` | Interactive setup: detect languages, configure ignore globs, optionally register MCP. |
| `codegraph build` | Walk the repo, parse with tree-sitter, write / update `graph.db`. |
| `codegraph analyze` | Run all analysis passes and print a report (Markdown or JSON). |
| `codegraph query callers <sym>` | Reverse-BFS: who calls a symbol? |
| `codegraph query subgraph <sym>` | Induced subgraph around a symbol. |
| `codegraph query deadcode` | List unreferenced functions/classes. |
| `codegraph query untested` | List functions with no incoming calls from a test module. |
| `codegraph query cycles` | Show import/call strongly-connected components. |
| `codegraph viz` | Render the graph as Mermaid, interactive HTML (pyvis), or SVG (graphviz). |
| `codegraph explore` | Interactive subgraph explorer (terminal UI). |
| `codegraph serve` | Launch the web dashboard (default port 8000). |
| `codegraph review` | Graph-diff current branch vs baseline; output risk report. |
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
pytest -q                           # tests (~130 passing)
```

---

## Roadmap

See [`docs/plan.md`](docs/plan.md) for the full phased roadmap.

---

## License

[MIT](LICENSE) © mochan
