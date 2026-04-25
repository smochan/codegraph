# LinkedIn post drafts

Three variants — pick whichever lands best, edit freely. Add a dashboard
screenshot or short Loom before posting; LinkedIn surfaces posts with
visuals far more aggressively.

---

## 🚀 Variant 1 — short, punchy, builder-tone

> Just shipped **codegraph 0.1.0** — a language-agnostic code graph
> builder, PR risk reviewer, and MCP server for Claude Code. All in one
> CLI, single SQLite store, no daemon.
>
> Why I built it: I kept asking my AI assistant questions like *"who
> calls this?"* and *"what's the blast radius of changing this
> function?"* and watching it `grep` the repo. Grep doesn't understand
> calls, imports, or inheritance. So I gave it a graph.
>
> What it does:
> 🧠 Parses your repo with tree-sitter into a queryable graph
> 🔍 Analysis: dead code, cycles, hotspots, untested, blast radius
> 🚦 PR review: graph diff vs baseline + YAML rules + SARIF output
> 🤖 MCP server with 10 tools — Claude Code talks to it directly
> 📊 Web dashboard: HLD navigator, animated focus graph, light/dark
>
> Open source, MIT, runs entirely offline.
>
> 👉 https://github.com/smochan/codegraph
>
> #ai #devtools #opensource #claudecode #mcp #python

---

## 🛠 Variant 2 — story-led, longer

> A few weeks ago I noticed the same friction over and over: every time
> I asked Claude Code "*who calls this function?*" or "*what's safe to
> delete in this module?*", it would `grep` the repo and guess. Decent
> for one-off questions, dangerous for refactors.
>
> Code is a graph. Functions call functions, classes inherit, modules
> import — none of that is text. So I built **codegraph** — a tiny
> single-binary tool that parses any repo with tree-sitter, stores the
> result in one SQLite file, and exposes it through:
>
> • A CLI (`build`, `analyze`, `query`, `review`)
> • A web dashboard with an HLD-style navigator and animated focus graph
> • An MCP server (10 tools) that plugs straight into Claude Code
>
> The PR-review side is the part I'm most excited about: snapshot a
> baseline graph, diff against your branch, score risk (high fan-in,
> introduced cycles, removed-but-still-referenced symbols, …), and emit
> Markdown / JSON / SARIF for GitHub code scanning. There's an optional
> pre-push hook that gates on severity.
>
> 0.1.0 ships today — Python, TypeScript, JavaScript on the parser
> side; Go / Java / Rust are next. 130 tests, mypy strict, MIT.
>
> If you've ever wanted your AI agent to actually understand the code
> it's editing, give it a try. Feedback and PRs welcome.
>
> 🔗 https://github.com/smochan/codegraph
>
> #ai #aiagents #devtools #opensource #python #softwareengineering #claudecode

---

## 🎯 Variant 3 — comparison-led (great for the "Why another tool?" crowd)

> If you've tried to give an LLM context about a real codebase, you've
> probably hit the same wall I did: pasting files works at toy scale,
> RAG-on-files hallucinates structure, and Sourcegraph is overkill
> (and cloud-coupled) for most teams.
>
> Today I'm releasing **codegraph 0.1.0** — a lightweight, local-first
> alternative.
>
>   ┌──────────────────────────────────────────────────────────────────┐
>   │  codegraph builds a SQLite graph of your code, then lets:        │
>   │   • humans browse it via a web dashboard with HLD navigation     │
>   │   • CI gate PRs on risk score, cycles, and rule violations       │
>   │   • AI agents (Claude Code via MCP) ask precise structural       │
>   │     questions instead of grepping                                │
>   └──────────────────────────────────────────────────────────────────┘
>
> No daemon. No cloud. No telemetry. One SQLite file you can commit
> alongside your repo if you want.
>
> I'd love feedback — especially from anyone running multi-language
> monorepos or building dev-time AI agents.
>
> 🔗 https://github.com/smochan/codegraph
> ⭐ if you'd use this
>
> #ai #mcp #devtools #opensource #claudecode #codequality #python

---

## Suggested visuals (in order)

1. **Dashboard hero** — full-page screenshot of the HLD page (system
   context + layered architecture + navigator with focus graph). Light
   or dark mode, your call. Make sure the focus graph has callers /
   callees visible.
2. **PR review output** — `codegraph review --format md` rendered as
   GitHub markdown, with a couple of high-severity findings.
3. **MCP in Claude Code** — short Loom of asking Claude "who calls
   `foo`?" and Claude calling `codegraph.callers` instead of grepping.

---

## Pre-publish checklist

- [ ] Pushed `v0.1.0` tag (`git push origin v0.1.0`)
- [ ] GitHub Release looks right (CHANGELOG.md as body, `dist/*` attached)
- [ ] Dashboard screenshot recorded and saved as `docs/images/dashboard.png`
- [ ] README placeholder image replaced with the real screenshot
- [ ] (Optional) Posted to PyPI; verified `pip install codegraph-py`
- [ ] LinkedIn variant chosen, screenshot attached, scheduled or posted
