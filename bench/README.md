# polycodegraph benchmark harness

Reproducible cross-tool benchmark: how well do graph-for-LLM code-review tools (and a plain-LLM control) actually do on real open-source repositories?

## What this is

Two passes per target repo:

- **Pass A — Review the diff.** Rewind to the parent commit, hand the diff for the next merged PR to each tool, capture findings. Score against a ground-truth heuristic (follow-up commits, GitHub issues, reverts).
- **Pass B — Reproduce the work.** Rewind to the parent commit, hand each tool the PR title + description, ask it to produce the change. Score on compile/lint, diff similarity, and tests-pass on the original test suite.

## Comparison set (v1)

- `polycodegraph` (system under test)
- `code-review-graph` (tirth8205)
- `better-code-review-graph` (n24q02m)
- `GitNexus`
- `JudiniLabs/mcp-code-graph`
- `RepoMapper`
- `Graphify`
- **Plain-LLM control:** Claude + GPT-class LLM with the diff only, no graph.

Commercial LLM PR reviewers (CodeRabbit etc.) are deliberately excluded from v1 — different category, ToS risk, muddies the graph-vs-graph wedge story.

## How to run

```bash
# Smoke test against the bundled example
codegraph bench run --repo examples/cross-stack-demo --commits 1 --pass A

# Real run (after repos.yaml is finalized)
codegraph bench run --config bench/repos.yaml --pass A
codegraph bench run --config bench/repos.yaml --pass B
```

Results land in `bench/results/<run-id>/`:

- `raw.jsonl` — one line per (tool, commit, metric) tuple.
- `RESULTS.md` — human-readable summary regenerated from `raw.jsonl`.

## Reproducibility

- Each runner is a fresh process (Docker container in v2, plain subprocess in v1).
- LLM responses are cached on disk keyed by prompt hash so re-scoring is free.
- Random seeds fixed where the tool exposes them.
- Budget caps in `budget.yaml` are hard limits — the harness aborts a runner that exceeds them.

## Ground-truth heuristic (Pass A)

A finding is a **true positive** if any of:

1. A follow-up commit within 30 days touches the same lines and references `fix`, `bug`, or `revert`.
2. A GitHub issue referencing the target commit is filed within 60 days.
3. The commit itself was reverted.

Ground truth is fuzzy. We acknowledge this in `RESULTS.md` and hand-label a 20-PR calibration subset.

## Methodology disclosures

This benchmark is run by the maintainer of polycodegraph. To keep it honest:

- All scripts live in this directory. Every reported number is reproducible from `raw.jsonl`.
- External-tool runners shell out to the upstream tools as a user would — no custom forks.
- We publish *failures* too: if polycodegraph misses a bug another tool catches, it goes in the table.
- Cost / latency / setup-time are measured the same way for every tool, including ours.

## Status

- [x] Harness skeleton + scoring + ground-truth labeler
- [x] polycodegraph runner (Pass A)
- [x] plain-LLM runner (Pass A)
- [ ] External-tool runners (stubbed — see `runners/<tool>/README.md` for wiring TODO)
- [ ] Pass B (generation) runner — skeleton only in v1
- [ ] First real OSS run + `RESULTS.md`
