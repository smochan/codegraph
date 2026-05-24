# Session Handoff — polycodegraph launch + v0.1.1 fix + v0.1.2 backlog

**Last update:** 2026-05-25
**Branch state:** `main` at `3b88d00`, tagged **`v0.1.1`** (live on PyPI)
**Predecessor handoff:** `.planning/SESSION_HANDOFF_BENCH.md` (bench chapter, 2026-05-21)

---

## TL;DR

The Claude-Code-style bench, README rewrite, and LinkedIn launch artifacts (Version G/H) all shipped through PR #43 + #44. A user testing the freshly-published 0.1.0 on a JS/TS React Native repo (`calybe-copy`) found that `codegraph init` never actually wrote `.mcp.json` despite the prompt — broke the README's "Claude Code + Cursor auto-pick up polycodegraph" claim. **Fixed and released as 0.1.1** (PR #45). 

LinkedIn post (Version G2 final, with three images: hero benchmark, DF4 GIF, MCP card) is **scheduled to publish 2026-05-24 Sun 10:30 AM** from the user's account. The on-the-day debugging surfaced **8 v0.1.2 backlog items** that are tracked below but not yet implemented.

---

## What shipped on 2026-05-23 → 2026-05-24

### v0.1.0 → v0.1.1 (live on PyPI)

- **PR #45** merged to main 2026-05-24 ~05:32 UTC.
- Tag `v0.1.1` pushed → GitHub Actions OIDC workflow published to PyPI in ~25s.
- Verified on `pypi.org/project/polycodegraph/` (latest = 0.1.1).
- Single fix in scope: `codegraph init` now actually writes `.mcp.json` when the user accepts the "Register MCP server" prompt. Three behaviours: creates fresh file, merges into existing, preserves user-customised `codegraph` entry. See `CHANGELOG.md` `## [0.1.1]` for the migration note.
- **Critical code:** `codegraph/cli.py:_write_project_mcp_json(repo_root)` (~50 LOC, ~line 247-300) — wired into the init flow at the bottom of the `init` command body.

### LinkedIn launch artifacts (in repo)

- `bench/LINKEDIN_POST.md` — final post is **Version G** (emoji-paced, comparison table, community ask). Three variations G1 short / G2 medium / G3 long. **User picked G2** and made minor edits (changed "two days" → "~4 weeks", "incumbents" → "what's already out there", added repo-README URL after global-config caveat, removed `**bold**` since LinkedIn doesn't render markdown). The polished version with strategic Unicode bold for the "3x cheaper, 4x faster" line is the final ship.
- **Image attachments (in order):** `docs/images/hero_benchmark.png` → `docs/images/df4_trace.gif` → `docs/images/mcp_output_card.png`. Optionally `docs/images/moat.png` as a 4th.
- All four images are reproducible from `scripts/render_hero_benchmark.py`, `scripts/assemble_df4_gif.py`, `docs/diagrams/moat.mmd`, and the HTML template documented in `docs/RECORDING_GUIDE.md`.

---

## Canonical CLAUDE.md / AGENTS.md snippet (user paste-target)

The user surfaced a real UX problem during calybe-copy testing: even with polycodegraph's MCP registered, Claude Code defaulted to grep instead of reaching for `find_symbol`. Fix is a small section the user pastes into their project's `CLAUDE.md` (or `AGENTS.md` for Codex / Cursor experimental support). Keep this snippet verbatim:

```markdown
## polycodegraph

This project has polycodegraph installed and registered via `.mcp.json`.
For any question about code structure, prefer polycodegraph's MCP tools
over `Grep` / `Read` / `Glob`:

- "Where is X defined?" → `mcp__codegraph__find_symbol(query: "X")`
- "Who calls Y?" → `mcp__codegraph__callers(qualname: "Y")`
- "What does Z depend on?" → `mcp__codegraph__callees(qualname: "Z")`
- "What breaks if I change this?" → `mcp__codegraph__blast_radius(qualname: "...")`
- "Trace an HTTP request end-to-end" → `mcp__codegraph__dataflow_trace(method_path: "GET /api/...")`
- "What's untested?" → `mcp__codegraph__untested()`
- "Any dead code?" → `mcp__codegraph__dead_code()`

Each tool returns a small focused subgraph (~20-50 tokens). Fall back
to grep only for free-text searches across comments / config / strings,
or when polycodegraph returns no hits.
```

v0.1.2 should ship this snippet via a new `codegraph install` subcommand (see backlog item below) so users don't have to find and paste it manually.

---

## v0.1.2 backlog (8 items, all surfaced during launch-day debugging)

| # | Item | Why | Effort |
|---|---|---|---|
| 1 | **`init` writes CLAUDE.md / AGENTS.md guidance** | Without this, agents default to grep and silently bypass polycodegraph. Caught on calybe-copy. Same pattern as graphify's `graphify claude install` and code-review-graph's `code-review-graph install`. | ~1 hr |
| 2 | **Auto-populate ignore patterns from detected language + framework** | When init sees `package.json` with `react-native`, auto-add `ios/Pods`, `android/build`, `node_modules`, etc. Eliminates the "type y for yes" footgun where users mis-type the ignore-patterns prompt (user hit this on calybe-copy → ignore list ended up as `[- y]`). | ~1 hr |
| 3 | **Auto-prune `.codegraph/explore/` + size cap on pyvis cache** | `codegraph serve` generates pyvis HTML per explored function, never prunes. Long-lived projects can hit 100-200 MB. Add LRU eviction at configurable size cap (default 50 MB), `codegraph clean` subcommand, status output showing current cache size. | ~2 hr |
| 4 | **Remove dead `mcp:` block from `.codegraph.yml` schema** | `mcp.enabled: false` is vestigial — no code path reads it. Confusing next to active `register_mcp: true`. Remove from `config.py` defaults; ignore on load if 0.1.x configs still have it. | ~30 min |
| 5 | **Better "graph not built yet" error from MCP server** | When Claude Code calls an MCP tool and `.codegraph/graph.db` doesn't exist, return a clear actionable error: `"polycodegraph: no graph found at .codegraph/graph.db. Run \`codegraph build\` in the repo root first."` Currently Claude paraphrases as "workspace is empty" which is misleading. | ~30 min |
| 6 | **`workspace_state` should distinguish "not configured" from "no repos"** | When `~/.codegraph/workspace.yml` doesn't exist, `workspace_state` returns empty repo list which makes LLMs assume the whole install is broken (cascade-confusion observed on calybe-copy). Should return `{status: "workspace_not_configured", message: "...local-graph MCP tools work independently..."}`. | ~45 min |
| 7 | **`semantic_search` / `hybrid_search` should distinguish "not built" from "not enabled"** | When `codegraph embed` hasn't run, these tools return "no embedding index" which sounds catastrophic. Soft-fail with: `"Optional feature not enabled. Run \`codegraph embed\` (~140 MB, ~30s) to enable. Structural query tools work without embeddings."` Same shape as #6. | ~45 min |
| 8 | **Fix repomapper bench runner install on Python 3.14** | `aider-chat` (transitive dep of repomapper) won't build on 3.14 due to `setuptools.build_meta` import. Fix: install `setuptools` + `wheel` explicitly into the repomapper venv before installing `aider-chat`, OR pin the bench's repomapper venv to Python 3.11. This is bench-side only — doesn't affect end users. | ~30 min |

**Total v0.1.2 scope:** ~7 hours of work. Items 1-7 are user-facing polish triggered by the launch-day testing. Item 8 is bench-harness cleanup carried over from the agent-bench chapter.

---

## What was tested + verified working on launch day (2026-05-24)

| Surface | Status | How verified |
|---|---|---|
| `pipx install polycodegraph` → 0.1.1 | ✅ | Live on pypi.org, user installed on Windows / calybe-copy |
| `codegraph init` writes `.codegraph.yml` | ✅ | Visible in user's file explorer screenshot |
| `codegraph init` writes `.mcp.json` (the 0.1.1 fix) | ✅ | Visible in user's file explorer + terminal output confirmed |
| `codegraph build` parses TS/JS repo | ✅ | 1891 scanned, 299 parsed, 2624 nodes, 7012 edges, 23.67s on calybe-copy |
| Cursor / Claude Code auto-picks up `.mcp.json` | ✅ | Claude Code in calybe-copy successfully called `find_symbol` after user paste of the CLAUDE.md snippet |
| MCP tools return real data | ✅ | `mcp__codegraph__find_symbol("OtaAssetManager")` returned correct file + role classification |

---

## What is still wrong / known footguns (file as v0.1.2 issues on GitHub)

These are the items the user hit during launch-day testing that we *didn't* fix in 0.1.1:

1. **`codegraph init`'s "Extra ignore patterns" prompt is free-text not yes/no** — user typed `y` thinking it was yes/no, got `ignore: [- y]` in the YAML. Footgun. → backlog item #2 (smart auto-ignore) eliminates the prompt entirely for common cases.
2. **`mcp.enabled: false` next to `register_mcp: true`** — looks contradictory, confused the user. → backlog item #4.
3. **Claude Code defaults to grep even with polycodegraph MCP registered** — without CLAUDE.md hint, agents don't know to prefer polycodegraph for structural queries. → backlog item #1 + CLAUDE.md snippet above.
4. **MCP server returns empty/confusing errors when graph not built or embeddings not run** — Claude cascades into "everything is broken" interpretation. → backlog items #5/6/7.
5. **`.codegraph/explore/` grows without bound** as `codegraph serve` is used. → backlog item #3.

---

## How to pick this up cold

```bash
git checkout main && git pull
# verify 0.1.1 still shipping
curl -s https://pypi.org/pypi/polycodegraph/json | python3 -c "import json,sys; print(json.load(sys.stdin)['info']['version'])"
# pick a v0.1.2 item from the backlog table above, branch off main, work through, PR
```

The bench harness (`bench/`, `codegraph bench agent` etc.) is unchanged from `SESSION_HANDOFF_BENCH.md` — that handoff still applies for anything bench-related. This handoff covers what happened *after* the bench was done: the launch readiness pass, the README rewrite ship, the 0.1.1 hotfix, and the v0.1.2 backlog the launch-day testing surfaced.
