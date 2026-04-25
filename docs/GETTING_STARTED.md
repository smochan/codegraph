# Getting started on a fresh machine

This is the one-stop guide for cloning `codegraph` to a new computer and
picking up exactly where we left off.

## 1. Clone

```bash
git clone https://github.com/smochan/codegraph.git
cd codegraph
```

That's it — everything is on `main`. There are no submodules and no
out-of-tree files. The state on GitHub is the source of truth.

## 2. Set up the dev environment

Requires Python **3.10, 3.11, or 3.12** (CI runs all three).

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
```

This installs:
- the `codegraph` CLI (editable, so edits to source apply immediately)
- runtime deps: typer, networkx, tree-sitter, pyvis, mcp, pyyaml, …
- dev deps: ruff, mypy, pytest, build, twine

## 3. Verify everything works

```bash
ruff check .
mypy --strict codegraph
pytest -q                          # should report 130 passed
codegraph --help                   # should list all subcommands
```

## 4. Build the graph for this repo and explore it

```bash
codegraph build
codegraph analyze
codegraph serve                    # opens http://127.0.0.1:8765
```

`codegraph serve` boots the polished web dashboard with the HLD navigator,
animated focus graph, theme toggle, and links into the pyvis explorers.

## 5. Try the MCP server (optional)

```bash
codegraph mcp serve --db .codegraph/graph.db
```

Or wire it into Claude Code (`~/.config/claude/mcp.json` or your client's
equivalent):

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

## 6. Try the PR review pipeline (optional)

```bash
codegraph baseline save            # snapshot current graph
# ...make some changes / build again...
codegraph build
codegraph review --format md       # show diff + risk findings
```

## Project layout

| Path | What lives there |
|---|---|
| `codegraph/cli.py` | All `typer` subcommands (entry point) |
| `codegraph/graph/` | SQLite store + NetworkX adapter + builder |
| `codegraph/parsers/` | tree-sitter language extractors (Python, TS, JS) |
| `codegraph/resolve/` | cross-file CALLS / IMPORTS resolver |
| `codegraph/analysis/` | metrics, cycles, hotspots, dead code, untested, blast radius |
| `codegraph/review/` | PR review: differ, risk, rules, baseline, hook |
| `codegraph/mcp_server/` | MCP stdio server (10 tools) |
| `codegraph/viz/` | mermaid, HLD, pyvis, dashboard payload |
| `codegraph/web/` | served dashboard (vanilla JS + Tailwind CDN + D3) |
| `tests/` | pytest suite (130 tests) |
| `docs/plan.md` | original roadmap |
| `docs/HANDOFF.md` | per-phase implementation notes |
| `CHANGELOG.md` | release notes for 0.1.0 |

## Workflow tips

- Always run `ruff check . && mypy --strict codegraph && pytest -q` before
  committing — these are the same gates CI enforces.
- `codegraph build` writes `.codegraph/graph.db` (gitignored). Re-run it
  whenever you change source so the dashboard / MCP / review reflect reality.
- `codegraph serve` rebuilds incrementally on click of the "Rebuild" button.

## Releasing 0.1.0

The local `v0.1.0` annotated tag has already been created. To publish:

```bash
git push origin v0.1.0
```

This fires `.github/workflows/release.yml` which builds wheels, runs
`twine check`, and creates a GitHub Release with `CHANGELOG.md` as the body.
If you've added `PYPI_API_TOKEN` to the repo secrets, it will also publish
to PyPI. Without the token it skips the publish step but still uploads the
artifacts to the GitHub Release.

## Known scope cuts

- Phase 2 (extra language extractors: Go / Java / Rust / C# / Ruby / PHP)
  is deferred. Adding one is mechanical — copy `codegraph/parsers/python.py`
  and adjust the tree-sitter queries.
- pyvis graphs use vis-network's own canvas; theme toggle is wired in but
  the underlying layout engine doesn't theme as cleanly as the dashboard.
