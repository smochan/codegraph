# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] - UNRELEASED

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
