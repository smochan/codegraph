# LinkedIn post draft — polycodegraph launch

> Draft for review. Pick a version, tweak the hook for your voice, and post.
> Numbers are from `bench/RESULTS_AGENT_LATEST.md` and reproducible via `codegraph bench agent`.

---

## Version A — the hook is the table (long-form, ~1200 chars + table)

I gave Claude Sonnet the same 10 questions about two real Python codebases. Then I changed only one thing — which MCP server it had access to.

→ Claude alone: **1/10 correct**, $0.15
→ Claude + polycodegraph MCP: **7/10 correct**, $0.33
→ Claude + a popular competitor MCP (code-review-graph): **1/10 correct**, $0.73

Same model. Same questions. Just the tool surface changed.

The questions were the basics every IDE assistant should be able to answer about a fresh codebase:
- Where is symbol X defined?
- Who calls Y?
- What does Z depend on?
- Which functions have no tests?
- Are there any cycles?

The two codebases:
- polycodegraph (my own — dogfooded)
- FastAPI (~30k LOC, MIT, you've probably seen it)

What surprised me wasn't that Claude-alone struggled — of course it can't answer code-specific questions without access to your repo. What surprised me was that **the competitor MCP spent ~3× more tokens per query and answered no better than Claude with no tools at all**. Its 30 verbose tool schemas pre-burn ~30k tokens of Claude's context before a single useful tool call happens.

polycodegraph's wedge isn't a fancier graph algorithm. It's:
1. Each tool returns a small focused subgraph (~20-50 tokens), not whole files
2. Tool schemas stay tight, so registering them doesn't bloat the prompt
3. Decorator-aware, role-classified (HANDLER / SERVICE / COMPONENT / REPO), so Claude gets the right *shape* of context for the question

Open source, MIT, on PyPI. The benchmark harness is also OSS — every number above is reproducible with one command:
`codegraph bench agent`

GitHub: github.com/smochan/polycodegraph

I'm not going to pretend 10 questions on 2 repos is a paper. It's a starting point. If you want to add your repo to the suite or run it against a different competitor, PRs welcome.

#claudecode #cursor #mcp #developertools #ai

---

## Version B — punchy, image-first (~600 chars, run with a screenshot of the table)

Same LLM. Same 10 questions. Only the MCP server changes.

🔴 Claude alone: 1/10 correct
🟢 Claude + polycodegraph: 7/10 correct
🟡 Claude + popular competitor MCP: 1/10 correct, 2× the cost

I built polycodegraph because I wanted Claude Code to actually *understand* my repo — not just grep through it. Then I built a benchmark to test that claim. The benchmark is what made me delete most of my marketing copy.

PyPI: `polycodegraph` · MIT · works with Claude Code, Cursor, Windsurf
Repo + reproducible harness: github.com/smochan/polycodegraph

#claudecode #cursor #mcp

---

## Version C — story-first ("I was wrong" framing, ~1000 chars)

I spent two days building a code-graph tool that I was sure would beat the AI-PR-review incumbents. Then I built a benchmark to prove it.

The first benchmark made me look bad. polycodegraph's CLI returned fewer findings than competitors. Felt good for them, bad for me.

Then I realised I was measuring the wrong thing. People don't run my CLI — they let Claude or Cursor call it via MCP. So I rebuilt the benchmark around that.

Same Claude Sonnet. Same 10 questions about 2 real codebases (mine + FastAPI). Only the registered MCP changes.

→ Claude alone: 1/10 correct
→ Claude + polycodegraph: 7/10 correct
→ Claude + a popular competitor MCP: 1/10 correct at 2× the cost (its 30 verbose tool schemas pre-burn Claude's context before any useful tool call)

The numbers don't owe me anything — I'd ship the post even if polycodegraph had lost. The win came from changing the *question*, not the tool.

Repo + reproducible bench: github.com/smochan/polycodegraph

#mcp #claudecode #ai

---

## Suggested image to attach

Screenshot the headline table from `bench/RESULTS_AGENT_LATEST.md`. Cropping recommendation:

```
| Configuration | Correct | Tokens in | Cost (USD) |
|---|---:|----:|----:|
| baseline (Claude alone) | 1/10 | ~960 | $0.15 |
| + polycodegraph MCP | 7/10 | ~77,000 | $0.33 |
| + code-review-graph MCP | 1/10 | ~222,000 | $0.73 |
```

(Numbers above are totals across both repos. The committed `bench/RESULTS_AGENT_LATEST.md` has the per-repo breakdown.)

---

## Caveats to acknowledge in comments if asked

- 10 questions, 2 repos. Not a paper. Designed to be extended via `bench/queries.yaml`.
- code-review-graph crashed on 2 of 10 queries (Anthropic 400 on edge-cased tool output); those weren't counted as failures-by-incorrectness, just dropped from cost+token totals.
- Better-code-review-graph, GitNexus, JudiniLabs not in the agent bench because of MCP-host-wrapper / license / staleness reasons documented in `bench/runners/`.

---

## Optional follow-up posts (if you want to compound)

1. **"How I almost shipped misleading marketing"** — the story-first version, lead with the *first* benchmark that made polycodegraph look bad, then the pivot to the agent-style one. Vulnerable + technical. Strong second post.
2. **"Day in the life of polycodegraph"** — short video showing one query running across all three configs side by side, in Claude Code's actual UI. Anchors the numbers to a visible experience.
3. **"The 17 token reply"** — narrow on the token-efficiency story. Pair with a 30-second clip showing polycodegraph's reply (a tiny subgraph) vs the competitor's (a 30k-token tool-schema dump).
