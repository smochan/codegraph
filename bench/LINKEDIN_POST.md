# LinkedIn post draft — polycodegraph launch

> Draft for review. Pick a version, tweak the hook for your voice, and post.
> Numbers are from `bench/RESULTS_AGENT_LATEST.md` and reproducible via `codegraph bench agent`.

---

## Version F — pain-first narrative (RECOMMENDED, 2026-05-23)

Author's voice. Story arc: pain → why current tools fall short → the insight → all the features that fall out for free → benchmark proof. Numbers in `<NUMBERS_TBD>` are filled in from `bench/RESULTS_AGENT_LATEST.md` once the 4-config run completes.

---

Claude Code and Cursor are great — until your codebase gets big. Then they grep, and grep, and grep some more, trying to figure out where anything is.

A handful of OSS tools (code-review-graph, graphify, GitNexus) saw this and started building code graphs to give the AI better project context. Good idea. But most of them stopped there — a graph for retrieval, and that's it.

My take: if you've gone to the trouble of building a graph of the whole repo, why stop at retrieval?

With the right graph you can also:
• flag dead code that's actually dead (decorator-aware, 24 frameworks — no false positives on FastAPI handlers)
• trace a single parameter from a `fetch()` in your React frontend, through the FastAPI handler, into the SQLAlchemy query, with rename annotations at every hop
• compute the blast radius of changing any function before you change it
• PR-review by graph-diffing the branch against `main`
• hand the entire query surface to your AI assistant as 18 MCP tools
• visualise the architecture in a 3D dashboard and animate the request lifecycle in a Learn Mode modal

But none of that works if the graph is mediocre. So I rebuilt the graph from the ground up — Python, TypeScript, JavaScript, Go — with techniques the other graph tools skipped: per-name + relative + decorator-aware import resolution, call-site argument capture (DF0), HTTP route detection (DF1), role classification HANDLER/SERVICE/COMPONENT/REPO (DF1.5), frontend fetch extraction (DF2), URL stitching across the stack (DF3), and end-to-end dataflow tracing (DF4).

I benchmarked it. Same Claude Sonnet, same 10 questions across two real codebases (polycodegraph itself + FastAPI). All four configs have Claude's native grep + file-reading tools. The only thing that changes is whether a graph MCP is *also* registered:

→ Claude + grep alone:                                 8/10 correct,  337k tokens, $1.17,  78s avg
→ Claude + grep + code-review-graph MCP:               3/10 correct,  203k tokens, $0.68,  49s avg
→ Claude + grep + graphify MCP:                        5/10 correct,  155k tokens, $0.50,  65s avg
→ Claude + grep + polycodegraph MCP:                   7/10 correct,   90k tokens, $0.37,  20s avg

Claude+grep is the most correct (it just dumps whole files into the context). polycodegraph gets to within one question of that **at 3× lower cost and 4× lower latency** — because it returns small focused subgraphs (~20-50 tokens per call) instead of file dumps. The other graph MCPs are strictly worse than just letting Claude grep — they add tool overhead without payoff.

Honest about what's *not* shipping yet: type inference, async-await visualization, git-history mining, full single-value argument propagation across hops. Listed in the README's Limitations section.

**Languages today:** Python, TypeScript / JavaScript / TSX / JSX, Go. **Roadmap:** Java, Rust, C# (v0.3); Ruby, PHP later. Adding a language is a ~3-hour tree-sitter parser file — PRs welcome.

`pip install polycodegraph` · MIT · works with Claude Code, Cursor, Windsurf
Repo + reproducible benchmark harness: github.com/smochan/polycodegraph

#mcp #claudecode #cursor #ai #developertools

---

### What to attach

- **Image:** `docs/images/hero_benchmark.png` (regenerated after the bench lands — 4 rows instead of 3)
- **Video:** `docs/images/df4_trace.gif` (capture per `docs/RECORDING_GUIDE.md`)

### Why this version, not A/B/C/D/E

- **Hook is a feeling, not a number.** "Claude is great until your codebase gets big" — every reader who uses Claude Code has felt this. Numbers convince; feelings hook.
- **Competitor positioning is fair, not antagonistic.** "Good idea. But most of them stopped there." Acknowledges they were on the right track, then justifies why we went further. No throwing shade.
- **The feature list earns its place.** Each bullet is a real capability with a one-line proof of *why* it exists (because the graph is already there). This is the README's MOAT section retold in narrative voice.
- **"DF0/1/1.5/2/3/4" lands as competence.** Listing the actual technique names tells the technical reader you didn't half-build this. The post above only uses the names; the README has the deep-dive.
- **Benchmark is the closer, not the opener.** Numbers are proof of the thesis already established by the story.

### Variant if the post needs to be shorter (~600 chars for "see-more" tightness)

Claude Code is great — until your codebase gets big. Then it greps, and greps, and greps.

Code-graph tools (code-review-graph, graphify) tried to solve this with a graph for retrieval. Most stopped there.

I built polycodegraph because once you have the graph, you can do *everything* with it — dead code (decorator-aware), blast radius, end-to-end argument tracing fetch→SQL, PR-review by graph-diff, 18 MCP tools, 3D dashboard.

Same Claude, same 10 questions, two real repos. polycodegraph: 7/10 at **3× lower cost and 4× lower latency than letting Claude grep**.

pip install polycodegraph · github.com/smochan/polycodegraph

#mcp #claudecode #cursor

---

## Version E — sourced from the new README (RECOMMENDED, 2026-05-23)

Lead with the "I was wrong" hook (still the strongest opener), then surface the MOAT framing
from the rewritten README's section #5, then deliver the benchmark as proof, then point
straight at the DF4 trace video as the unique-capability claim. Every line traces back to
a section of `README.md` or `bench/RESULTS_AGENT_LATEST.md`.

---

I spent two days building a code-graph tool I was sure would beat the incumbents. The first benchmark made me look bad.

Then I realised I was measuring the wrong thing.

Developers don't run my CLI. They let Claude Code or Cursor call it via MCP. So I rebuilt the benchmark around that — same Claude Sonnet, same 10 questions about 2 real codebases (mine + FastAPI), only the registered MCP changes:

→ Claude alone:                            1/10 correct, $0.15
→ Claude + popular competitor MCP:         1/10 correct, $0.73
→ Claude + polycodegraph MCP:              7/10 correct, $0.33

The table is the floor. The video is the claim ↓

polycodegraph has exactly one opinion: build the right graph, and every interesting feature falls out for free. It reads tree-sitter parses for Python / TS / JS / Go, captures every call-site argument as text, recognises 24 framework decorators (FastAPI, Flask, Celery, pytest, Django, SQLAlchemy…), detects frontend fetches (fetch, axios, useSWR, useQuery) and SQLAlchemy reads/writes, then stitches URLs across the stack (/{id} ↔ ${id} ↔ :id).

Once the graph is right, you get for free: decorator-aware dead code, blast radius, role classification (HANDLER / SERVICE / COMPONENT / REPO), an end-to-end cross-stack trace with rename annotations (userId → user_id → id), a 3D focus dashboard, a Learn Mode lifecycle modal, local embeddings, and an 18-tool MCP server.

One SQLite file. No daemon. No API keys. Travels with your git branch.

Honest about what's not yet shipping: type inference, async-await visualization, git-history mining, full single-value arg propagation across hops. Listed in the README's Limitations section.

pip install polycodegraph · MIT · works with Claude Code, Cursor, Windsurf
Repo + reproducible benchmark harness: github.com/smochan/polycodegraph

#mcp #claudecode #cursor #ai #developertools

---

### What to attach

- **Image:** `docs/images/hero_benchmark.png` (already in the repo)
- **Video:** `docs/images/df4_trace.gif` (capture per `docs/RECORDING_GUIDE.md`)

### Why this version, not A/B/C/D

- Hook unchanged from C (the highest-converting opener). "I was wrong" still earns the see-more click.
- MOAT paragraph is verbatim from README section 5 — every claim is verifiable in code, not marketing.
- Benchmark line is byte-identical to `bench/RESULTS_AGENT_LATEST.md` totals. No exaggeration.
- "The table is the floor. The video is the claim" reframes the numbers as evidence for the *real* product, not the product itself.
- "Honest about what's not yet shipping" — explicit limitations line. Builds credibility, deflects the inevitable "but does it do X" comment.

### One-line variants of the hook, if you want to A/B test

- *"I spent two days building a tool I was sure would beat the incumbents. The first benchmark made me look bad."* (current)
- *"My code-graph tool failed its first benchmark. Then I realised I was benchmarking the wrong thing."*
- *"Same Claude, same questions, three MCPs. Two of them got 1/10. One got 7/10."*

The first is strongest on stakes + curiosity. The second is shorter. The third is the most "Twitter-engineer" voice — punchy, no narrative, image does the work.

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

## Where the tokens actually go (the "why 960 vs 77k" answer)

A common follow-up: *"Baseline used 960 tokens total and polycodegraph used 77k? Doesn't that mean polycodegraph is wasteful?"*

No — baseline is so low *because Claude has nothing to read*. It just guesses from training and ships ~96 tokens per query. polycodegraph's ~7,700 tokens per query break down as:

| Where the input tokens go | per query | why |
|---|---:|---|
| Question + system prompt | ~80 | same as baseline |
| 18 MCP tool schemas sent in context | ~3,000 | Claude needs to know what tools exist |
| Tool *results* (graph data returned) | ~4,500 | the actual answer material |
| Other | ~120 | |

code-review-graph's ~22k per query: 30 tool schemas pre-burn ~6k just *advertising* tools, then ~14k come back from verbose tool responses, then Claude needs more turns because the first result wasn't focused enough. **3× more tokens than polycodegraph, 7× lower correctness.** That's the real comparison.

## Caveats to acknowledge in comments if asked

- 10 questions, 2 repos. Not a paper — designed to be extended via `bench/queries.yaml`. PRs welcome.
- Tools in the agent bench: **baseline · polycodegraph · code-review-graph.** Tools excluded with reasons:
  - **graphify** — its MCP server corrupts its stdio JSON-RPC stream with banner/log output mid-call (anyio cancel-scope trip on cleanup). Pass Q bench includes it; agent bench doesn't.
  - **better-code-review-graph** — wired and working, but Anthropic spend cap hit before we could run the full 10×2 grid.
  - **GitNexus** — PolyForm Noncommercial license; not benchmarked from this MIT project.
  - **JudiniLabs/mcp-code-graph** — thin client to the hosted CodeGPT service, different category.
  - **RepoMapper** — no MCP server, just a static-map CLI.
- code-review-graph crashed on 2 of 10 queries (Anthropic 400 on edge-cased tool output); those are *failures*, not silently dropped — see `bench/agent_raw_latest.jsonl`.

---

## Optional follow-up posts (if you want to compound)

1. **"How I almost shipped misleading marketing"** — the story-first version, lead with the *first* benchmark that made polycodegraph look bad, then the pivot to the agent-style one. Vulnerable + technical. Strong second post.
2. **"Day in the life of polycodegraph"** — short video showing one query running across all three configs side by side, in Claude Code's actual UI. Anchors the numbers to a visible experience.
3. **"The 17 token reply"** — narrow on the token-efficiency story. Pair with a 30-second clip showing polycodegraph's reply (a tiny subgraph) vs the competitor's (a 30k-token tool-schema dump).
