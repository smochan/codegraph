# Session Handoff — polycodegraph distribution (registry PRs + form submissions)

**Last update:** 2026-05-30
**Predecessor handoff:** `.planning/SESSION_HANDOFF_LAUNCH.md` (LinkedIn launch + 0.1.1 hotfix, 2026-05-24)
**Status:** paused — user wants to fix v0.1.2 polish items before pushing more public distribution.

---

## TL;DR

Three of the form-fill submissions are in review queues (glama / mcpservers.org / smithery). The four GitHub PRs (punkpeye, appcypher, analysis-tools-dev, sdras/awesome-actions) and the official `modelcontextprotocol/registry` publish are **drafted but not executed**. Verbatim entry text + insertion points are below — next session can copy-paste and ship in ~30 min once the v0.1.2 polish lands.

**Important:** all four fork clones lived in `/tmp/pcg-prs/` and will likely be wiped before pickup. Plan to re-fork at execution time; the prepared edits below are the source of truth, not the on-disk forks.

---

## What's submitted (in review queues)

| Target | URL | Status | Notes |
|---|---|---|---|
| **glama.ai/mcp** | https://glama.ai/mcp/servers | submitted 2026-05-25 | "Host MCP Servers" personalization picked. Repo auto-scans + returns score-badge URL `https://glama.ai/mcp/servers/smochan/polycodegraph/badges/score.svg` once approved. |
| **mcpservers.org** | https://mcpservers.org/submit | submitted 2026-05-25, ~12h review window | Free tier (skipped $39 premium). Category: Developer Tools. |
| **smithery.ai** | https://smithery.ai/new | submitted 2026-05-25 | Stdio Python server — if Smithery later requires a `smithery.yaml`, add one as a small follow-up commit. |

**Verification tip when next session resumes:**
- `curl -s https://api.pulsemcp.com/servers | jq '.[] | select(.name | contains("polycodegraph"))'` — checks pulsemcp ingest (only valid after Step 2 registry publish).
- glama: open https://glama.ai/mcp/servers/smochan/polycodegraph — 200 = listed.

---

## What's NOT done — pickup queue (in execution order)

### Step 1 — official `modelcontextprotocol/registry` publish (highest leverage; cascades to pulsemcp + mcp.so)

```bash
git clone https://github.com/modelcontextprotocol/registry ~/code/mcp-registry
cd ~/code/mcp-registry && make publisher
```

Draft `server.json` for polycodegraph (verify schema against `docs/server-json/` in the registry repo at execution time — fields may have evolved):

```json
{
  "name": "io.github.smochan/polycodegraph",
  "description": "Multi-language code-graph MCP server. 18 tools (find_symbol, callers, callees, blast_radius, dead_code, untested, dataflow_trace) for AI assistants. Tree-sitter parsing for Python / TS / JS / Go. Local-first, no API key required.",
  "version": "0.1.1",
  "repository": {
    "url": "https://github.com/smochan/polycodegraph",
    "source": "github"
  },
  "packages": [
    {
      "registry_type": "pypi",
      "identifier": "polycodegraph",
      "version": "0.1.1",
      "runtime_hint": "uvx",
      "transport": { "type": "stdio" }
    }
  ]
}
```

Then `./mcp-publisher publish --file server.json`. Follow the GitHub device-flow link for namespace verification. One publish → cascades to pulsemcp (~7-day SLA) + mcp.so (auto-backfill).

### Step 2 — PR: `punkpeye/awesome-mcp-servers` (~50k★, the big one)

- File: `README.md`, section `### 💻 Developer Tools` (~line 769 as of 2026-05-25).
- Insert between `skullzarmy/vibealive` and `snaggle-ai/openapi-mcp-server` (alphabetical by `owner/repo`).
- Use glama badge URL only after glama approval lands; if not yet live, drop the `[![...]]` block.

```
- [smochan/polycodegraph](https://github.com/smochan/polycodegraph) [![smochan/polycodegraph MCP server](https://glama.ai/mcp/servers/smochan/polycodegraph/badges/score.svg)](https://glama.ai/mcp/servers/smochan/polycodegraph) 🐍 🏠 🍎 🪟 🐧 - Multi-language code-graph MCP server. 18 tools — find_symbol, callers, callees, blast_radius, dead_code, untested, plus cross-stack `dataflow_trace` (HTTP request → handler → service → SQL). Tree-sitter parsing for Python / TS / JS / Go. Local-first, no API key required. In benchmarks, ~3× fewer tokens than Claude+grep at the same correctness.
```

PR title: `Add smochan/polycodegraph 🤖🤖🤖` (the robot trio triggers their fast-track per CONTRIBUTING.md).

### Step 3 — PR: `appcypher/awesome-mcp-servers`

- File: `README.md`, section `## 💻 Development Tools` (~line 381).
- Section is NOT alphabetical — append at end (before the `<br />` separator that precedes the next section header).

```
- [polycodegraph](https://github.com/smochan/polycodegraph) - 18 MCP tools for code-graph queries (find_symbol, callers, callees, blast_radius, dataflow_trace) across Python / TS / JS / Go. Local-first, no API key required.
```

### Step 4 — PR: `analysis-tools-dev/static-analysis`

- New file: `data/tools/polycodegraph.yml` (README is generated; do NOT edit README).

```yaml
name: PolyCodeGraph
categories:
  - meta
tags:
  - python
  - javascript
  - typescript
  - go
license: MIT
types:
  - cli
source: "https://github.com/smochan/polycodegraph"
description: >-
  Builds a queryable code graph from multi-language codebases using Tree-sitter,
  with per-name + decorator-aware import resolution and call-site argument
  capture. Exposes 18 MCP tools (find_symbol, callers, callees, blast_radius,
  dead_code, untested, dataflow_trace) for AI assistants. Local-first, no API
  key required.
```

### Step 5 — PR: `sdras/awesome-actions`

- File: `README.md`, section `### Code Quality` or `### Continuous Integration` — pick whichever already houses AI-review actions like `reviewdog`. Match neighbor format verbatim at execution time.
- Provisional draft:

```
- [polycodegraph](https://github.com/smochan/polycodegraph) - Code-graph-based PR review. Posts only the blast-radius subgraph for changed symbols, not whole-file dumps. Also runs as an MCP server inside Claude Code / Cursor.
```

---

## Explicit out-of-scope (don't do these)

1. **Unsolicited PRs adding polycodegraph's GitHub Action to other people's repos.** Universally treated as spam in OSS — every documented attempt at this pattern got mass-closed and damaged the project's reputation. The legitimate version is the awesome-actions catalogue PR (Step 5 above) where adding your entry IS the contribution.
2. **All Track 2 venues** (HN Show HN, Product Hunt, dev.to, MCP Discord, r/ClaudeAI, r/cursor, r/LocalLLaMA, Lobsters, Daily.dev) — user explicitly deferred until after v0.1.2 polish lands. Do not post anywhere until user reopens this scope.

---

## Why this is paused

User flagged that polycodegraph has v0.1.2-tier polish items still unresolved (the 8-item backlog in `.planning/SESSION_HANDOFF_LAUNCH.md`, task IDs #45-52). Pushing more public distribution before those land risks burning first impressions on users who hit the rough edges. Resume distribution after v0.1.2 (or at least the highest-impact init/UX items: #46 auto-ignore patterns, #51 CLAUDE.md snippet writer).

---

## How to pick up cold

```bash
# 1. Confirm submissions landed
open https://glama.ai/mcp/servers/smochan/polycodegraph
open https://mcpservers.org/   # search "polycodegraph"

# 2. Re-fork the four target repos (the /tmp/pcg-prs/ clones from last session are gone)
mkdir -p /tmp/pcg-prs && cd /tmp/pcg-prs
gh repo fork punkpeye/awesome-mcp-servers --clone
gh repo fork appcypher/awesome-mcp-servers --clone
gh repo fork analysis-tools-dev/static-analysis --clone
gh repo fork sdras/awesome-actions --clone

# 3. Apply each prepared entry above. Use this naming for all four PRs:
#    branch: add-polycodegraph
#    commit: docs: add polycodegraph entry
#    PR title (punkpeye only): Add smochan/polycodegraph 🤖🤖🤖
#    PR title (others): Add polycodegraph

# 4. Verify each PR's CI lint passes before stepping away.
```

---

## Related task IDs

- #56 ✅ glama submission
- #57 ✅ mcpservers.org submission
- #58 ✅ smithery submission
- #59 ⏳ official registry publish (this handoff = Step 1)
- #53 ⏳ PR: punkpeye/awesome-mcp-servers (Step 2)
- #54 ⏳ PR: appcypher/awesome-mcp-servers (Step 3)
- #55 ⏳ PR: analysis-tools-dev/static-analysis (Step 4)
- #60 ⏳ PR: sdras/awesome-actions (Step 5)

v0.1.2 polish prerequisites (from `.planning/SESSION_HANDOFF_LAUNCH.md`): #45–#52.

---

## Sources

- Research subagent inventory (2026-05-25 session) — registry list, entry formats, alphabetical insertion points verified against live README fetches.
- Plan file: `/Users/smochan/.claude/plans/okay-so-you-have-woolly-peacock.md` (approved 2026-05-25).
- `gh auth status` (2026-05-25): user `smochan`, scopes `repo` + `gist` — sufficient for all four PR forks.
