# LinkedIn post — codegraph 0.1.0 launch (post-ready)

> **Format note:** LinkedIn truncates the post body around 210 characters
> on mobile feed. The first sentence is the hook — it must land before
> the "see more" cut. Verify on desktop preview before posting.
>
> Attach the 5s silent loop (`loop_5s.mp4`) inline. Pin the
> tools-comparison comment 2 minutes after publishing.

---

## Main post

> Pick a function in your repo. See exactly what calls it and what it
> calls. Click any node to fold its neighbours in, click again to fold
> them back. External library calls stop at the boundary, so your code
> stays in focus instead of getting lost in a `requests.get` rabbit hole.
> That's the 3D focus-mode flow tracer in **codegraph 0.1.0**, shipping
> today.
>
> Along the way, the analyzer caught 451 false-positive dead-code
> findings on its own source. We fixed 5 categories of resolver bugs to
> get that down to 3 — and the 3 that remain are intentional public
> APIs, documented in code. The test suite grew from 147 to 202 passing
> across Python and JS. The 3 cycles in our own code are now reported
> with qualnames instead of opaque hashes, so we could actually discuss
> them: 2 are accepted (one is a deliberate UI redraw loop, one is a
> known static-resolver false positive against an MCP `Server.run`
> method), and 1 is tracked as a v0.1.1 follow-up. Honest engineering on
> the tool's own code, not a marketing claim.
>
> What it does: builds a graph of Python and TypeScript / JavaScript
> repos via tree-sitter; reports dead code with decorator-aware
> entry-point detection (Typer, FastAPI, Click, Celery, pytest, MCP —
> 24 framework decorators recognised); reports cycles, hotspots,
> untested functions; ships a CLI, a web dashboard with the 3D focus
> view, and an MCP server with 10 tools for Claude Code.
>
> What it does NOT do yet: argument-level data flow, service /
> component classification, cross-stack frontend → API → DB tracing.
> Those are the v0.2 wedge. Type inference is v0.3+.
>
> MIT, single SQLite file, no daemon.
>
> ```
> pip install codegraph-py
> ```
>
> Repo: https://github.com/smochan/codegraph
>
> Honest feedback welcome. Especially from people running multi-language
> monorepos or building dev-time AI agents.
>
> @Anthropic @Claude
>
> #AIagents #DeveloperTools #MCP #ClaudeCode #OpenSource #Python #TypeScript #CodeQuality

---

## Pinned comment (paste 2 minutes after the main post)

> A few people have asked how this differs from the existing
> code-graph tools. Honest short version:
>
> | Tool | Local-first | MCP-native | Decorator-aware dead code | 3D focus view | Cross-stack tracing |
> |------|:-:|:-:|:-:|:-:|:-:|
> | **codegraph** | ✅ | ✅ | ✅ | ✅ | v0.2 (planned) |
> | GitNexus | ✅ | partial | ❌ | ✅ | ❌ |
> | better-code-review-graph | ✅ | ❌ | ❌ | ❌ | ❌ |
> | JudiniLabs/mcp-code-graph | partial | ✅ | ❌ | ❌ | ❌ |
> | RepoMapper | ✅ | ❌ | ❌ | ❌ | ❌ |
> | Sourcegraph | ❌ (cloud) | ❌ | ❌ | partial | partial |
>
> The wedge in one sentence: **external calls stop at the boundary so
> your code stays in focus, and decorator-aware analysis means
> framework handlers don't show up as dead code.** The other tools each
> solve a slice; codegraph stitches the slices that matter for the AI
> assistant + local-machine loop, and the v0.2 bet is on cross-stack
> tracing.

---

## Reply templates (paste verbatim, edit per comment)

**"How does this compare to GitNexus?"**
> GitNexus is more mature on visualisation polish and is the reference
> in the space. codegraph is shaped differently: MCP-native from day
> one, decorator-aware dead-code detection across 24 framework
> decorators, single SQLite file you can commit alongside the repo, and
> the next version focuses on cross-stack data-flow tracing rather than
> deeper single-language graphs. Different bets.

**"Why not Sourcegraph?"**
> Sourcegraph is excellent at scale and team-wide. codegraph is for the
> developer-machine + AI-agent loop: nothing to deploy, no auth, the
> graph lives in `.codegraph/graph.db` next to the repo. If your team
> already runs Sourcegraph, codegraph isn't replacing it — it's a
> different layer.

**"Does it support {Go, Rust, Java}?"**
> Module-level today, function-level on the roadmap. Each language is a
> single tree-sitter mapping file — happy to take PRs, the Python
> extractor is the template.

**"How accurate is the call graph?"**
> Static, tree-sitter based, no type inference yet (that's v0.3+).
> Catches direct calls, imports, decorator edges, same-file ctor calls,
> nested-function call attribution, and `self.X.Y` chains cleanly.
> Misses dynamic dispatch and `getattr` patterns. The README has a
> "what it does NOT do yet" section — I'd rather be honest about the
> limits than oversell.

---

## Pre-publish checklist

- [ ] PyPI 0.1.0 live and `pip install codegraph-py` works on a clean venv
- [ ] 45s MP4 + 5s loop both exported and previewed on phone
- [ ] First ~210 chars of the post truncate at the right spot (test on
      LinkedIn mobile preview)
- [ ] @Anthropic and @Claude resolve to the right pages
- [ ] Hashtags spelled exactly — LinkedIn hashtags are case-insensitive
      but display the casing of the first use
- [ ] Repo README live with 0.1.0 status (already done)
- [ ] Pinned comment ready to paste 2 min after main post
- [ ] Calendar block 09:00–10:00 ET on posting day for the first-hour
      reach window
