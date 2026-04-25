# codegraph

> Language-agnostic code graph builder, analyzer, PR risk reviewer, and MCP server for Claude Code.

`codegraph` parses your repo with tree-sitter, builds a queryable graph of
files / classes / functions / variables / imports / calls / inheritance /
tests, and uses it to:

- 🔎 **Analyze** the whole project (dead code, cycles, untested hot paths, fan-in/out).
- 🚦 **Review PRs** by diffing your branch's graph against a baseline and scoring blast radius.
- 🖼️ **Visualize** the graph (Mermaid / interactive HTML / SVG).
- 🤖 **Power AI assistants** via an MCP server that returns *small, focused subgraphs* — perfect for Claude Code.

> ⚠️ Status: **pre-alpha**. APIs and CLI flags will change. See [plan](./docs/plan.md).

## Install (coming soon)

```bash
pip install codegraph-py            # PyPI distribution name
codegraph init                      # interactive setup
codegraph build
codegraph analyze
```

## Why another code graph tool?

| | codegraph | grep + IDE | Sourcegraph | code-review-graph |
|---|---|---|---|---|
| Multi-language via tree-sitter | ✅ | — | ✅ | partial |
| Self-hostable, single binary | ✅ | n/a | ❌ heavy | ✅ |
| MCP server for Claude Code | ✅ | ❌ | ❌ | ❌ |
| PR risk scoring + git hook | ✅ | ❌ | partial | ✅ |
| YAML rule packs (no code edits) | ✅ | n/a | ❌ | ❌ |
| MIT, fully open | ✅ | n/a | mixed | ❌ private |

## Supported languages (target v0.1)

Python, TypeScript, JavaScript, Go, Java, Rust, C#, Ruby, PHP. Adding more is a one-file extractor.

## License

MIT
