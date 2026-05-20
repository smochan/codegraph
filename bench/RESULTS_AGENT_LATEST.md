# Claude-Code-style agent benchmark — run `20260520T183244Z`

Host LLM: `claude-sonnet-4-6` (same across every configuration).
Only the MCP tools exposed to Claude change between configurations.

## Repo: `codegraph-self`

| Configuration | Correct | Avg turns | Avg tool-calls | Tokens in | Tokens out | Cost (USD) | Avg latency (s) |
|---|---:|----:|----:|----:|----:|----:|----:|
| `baseline` | 0/5 | 1 | 0 | 480 | 4659 | 0.0713 | 12.15 |
| `code-review-graph` | 0/5 | 3.8 | 3 | 144422 | 2306 | 0.4679 | 61.38 |
| `polycodegraph` | 4/5 | 2.4 | 1.4 | 36639 | 2851 | 0.1527 | 12.18 |

## Repo: `fastapi`

| Configuration | Correct | Avg turns | Avg tool-calls | Tokens in | Tokens out | Cost (USD) | Avg latency (s) |
|---|---:|----:|----:|----:|----:|----:|----:|
| `baseline` | 1/5 | 1 | 0 | 476 | 4944 | 0.0756 | 13.72 |
| `code-review-graph` | 1/5 | 2.3 | 1.3 | 78069 | 2048 | 0.2649 | 64.27 |
| `polycodegraph` | 3/5 | 2.6 | 1.6 | 40953 | 3505 | 0.1754 | 14.8 |

## How to read this

- Same host LLM across every row. Only the registered MCP tools change.
- `Tokens in` is the sum of context fed to Claude across the whole agent loop, including
  tool-result payloads. This is the number users actually pay for in real coding-assistant use.
- `Tokens out` is Claude's generated output across the loop.
- A query is correct if either the model's final answer or any tool-call output contains the expected hits.
