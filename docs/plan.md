# codegraph roadmap

See the working plan in the session for full details. Phases:

0. **Bootstrap** — repo, packaging, CI, CLI skeleton. ✅ in progress
1. **Core graph (MVP)** — schema, SQLite store, NetworkX adapter, Python + TS extractors, `init` + `build`.
2. **Language breadth** — JS, Go, Java, Rust, C#, Ruby, PHP extractors.
3. **Analysis** — blast radius, dead code, cycles, untested, hotspots, metrics.
4. **PR review** — differ, YAML rules, risk scorer, baseline backends, git hook.
5. **MCP integration** — `mcp serve` with focused subgraph tools for Claude Code.
6. **Visualization polish** — pyvis HTML, graphviz SVG.
7. **Release** — publish to PyPI, push to GitHub.
