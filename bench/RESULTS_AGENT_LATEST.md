# Claude-Code-style agent benchmark — run `20260523T143844Z`

Host LLM: `claude-sonnet-4-6` (same across every configuration).
Only the MCP tools exposed to Claude change between configurations.

## Repo: `codegraph-self`

| Configuration | Correct | Avg turns | Avg tool-calls | Tokens in | Tokens out | Cost (USD) | Avg latency (s) |
|---|---:|----:|----:|----:|----:|----:|----:|
| `claude+grep` | 5/5 | 5.8 | 16.6 | 264756 | 8387 | 0.9201 | 102.04 |
| `claude+grep+code-review-graph` | 2/5 | 2.5 | 2 | 118674 | 2557 | 0.3944 | 55.68 |
| `claude+grep+graphify` | 3/5 | 2.7 | 1.7 | 99233 | 991 | 0.3126 | 82.93 |
| `claude+grep+polycodegraph` | 4/5 | 2.4 | 1.4 | 43705 | 3391 | 0.182 | 22.05 |

## Repo: `fastapi`

| Configuration | Correct | Avg turns | Avg tool-calls | Tokens in | Tokens out | Cost (USD) | Avg latency (s) |
|---|---:|----:|----:|----:|----:|----:|----:|
| `claude+grep` | 3/5 | 3.7 | 4.3 | 71833 | 2563 | 0.2539 | 53.78 |
| `claude+grep+code-review-graph` | 1/5 | 2.3 | 2 | 84082 | 2442 | 0.2889 | 42.04 |
| `claude+grep+graphify` | 2/5 | 2.7 | 3.3 | 55287 | 1821 | 0.1932 | 46.46 |
| `claude+grep+polycodegraph` | 3/5 | 2.4 | 1.4 | 46347 | 3300 | 0.1885 | 17.98 |

## How to read this

- Same host LLM across every row. Only the registered MCP tools change.
- `Tokens in` is the sum of context fed to Claude across the whole agent loop, including
  tool-result payloads. This is the number users actually pay for in real coding-assistant use.
- `Tokens out` is Claude's generated output across the loop.
- A query is correct if either the model's final answer or any tool-call output contains the expected hits.
