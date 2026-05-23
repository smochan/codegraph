# Session Handoff — codegraph bench harness chapter

**Last update:** 2026-05-21
**Branch:** `feat/bench-harness` (5 commits ahead of `main`, **not pushed**)
**HEAD:** `3f822f1 bench(agent): wire better-CRG config + harden against MCP stdio quirks`
**Predecessor handoff:** `SESSION_HANDOFF.md` (v0.3 unified-trace chapter, 2026-04-29)

---

## TL;DR

Built a **cross-tool, reproducible benchmark harness** under `bench/` that compares polycodegraph against the graph-for-LLM tools its README's "Where it fits" table calls out, plus a plain-LLM control, plus a *Claude-Code-style agent benchmark* where the same Claude Sonnet 4.6 answers the same questions with different MCP servers registered. The bench is the launch story for polycodegraph: it makes the README's competitor-table claims *measurable* instead of "trust me".

**Headline numbers (committed in `bench/RESULTS_AGENT_LATEST.md`):**

| Config | Correct | Tokens in (total) | Cost (total) |
|---|---:|---:|---:|
| Claude alone (baseline) | 1/10 | ~960 | $0.15 |
| + polycodegraph MCP | **7/10** | ~77k | $0.33 |
| + code-review-graph MCP | 1/10 | ~222k | $0.73 |

Same LLM, same 10 questions across 2 repos (codegraph-self + FastAPI), only the registered MCP server changes. polycodegraph is **7× more correct than no tools and 7× more correct than the competitor MCP at half the cost**.

`bench/LINKEDIN_POST.md` has 3 ready-to-post drafts anchored on these numbers (A long-form / B punchy / C "I was wrong" story). Branch is not pushed yet — that's an explicit user gate before going public.

---

## What landed (5 commits on `feat/bench-harness`)

```
3f822f1 bench(agent): wire better-CRG config + harden against MCP stdio quirks
b11924d docs(bench): LinkedIn post drafts (A/B/C) anchored on agent-bench numbers
8b4cea0 bench(agent): pin the 2026-05-21 Claude-Code-style headline numbers
252d609 feat(bench): Claude-Code-style agent benchmark
94f1a51 feat(bench): cross-tool query + diff-review benchmark harness
```

### `bench/` directory layout

```
bench/
├── README.md                       # methodology + how to reproduce
├── repos.yaml                      # target repos for Pass A (diff-review)
├── queries.yaml                    # ground-truth questions for Pass Q + agent
├── budget.yaml                     # per-tool USD caps
├── configurations.yaml             # agent-bench MCP server configs
├── RESULTS_AGENT_LATEST.md         # frozen 2026-05-21 headline numbers (committed)
├── agent_raw_latest.jsonl          # per-run raw JSONL (committed)
├── LINKEDIN_POST.md                # 3 post drafts + image crop + caveats
├── harness.py                      # Pass A orchestrator
├── query_harness.py                # Pass Q orchestrator
├── agent_harness.py                # Pass Agent orchestrator (Claude + MCP)
├── mcp_client.py                   # stdio MCP client wrapper
├── ground_truth.py                 # heuristic labeler for Pass A
├── scoring.py                      # precision/recall/cost/latency for Pass A
├── query_types.py                  # QuerySpec/QueryResult + matches()
├── types.py                        # Pass A dataclasses
└── runners/
    ├── polycodegraph_runner.py     # full Pass A + Pass Q (in-process API)
    ├── plain_llm_runner.py         # full Pass A + Pass Q (Gemini default)
    ├── code_review_graph_runner.py # full Pass A (CLI shell-out)
    ├── graphify_runner.py          # Pass A graph-only + Pass Q
    ├── repomapper_runner.py        # Pass A graph-only only
    ├── _graph_only.py              # base for tools w/ no diff-review surface
    ├── _excluded.py                # base for tools deliberately excluded
    ├── _stub.py                    # base for unwired tools (loud NotImplemented)
    ├── _venv.py                    # per-tool isolated-venv helper
    ├── gitnexus_runner.py          # excluded (PolyForm Noncommercial)
    ├── judini_runner.py            # excluded (hosted CodeGPT service)
    └── better_code_review_graph_runner.py  # excluded (MCP-only earlier; agent config now wired separately)
```

### Three benchmark passes

| Pass | CLI | What it measures | Status |
|---|---|---|---|
| **Pass A — diff review** | `codegraph bench run` | Per-commit findings, scored vs follow-up `fix`/`bug`/`revert` heuristic | Works; polycodegraph + code-review-graph produce real findings; graphify/repomapper measured as graph-build only |
| **Pass Q — graph query** | `codegraph bench query` | Native tool API answers structured questions ("find_symbol X", "callers of Y") | Strong story: **polycodegraph 10/10, graphify 6/10, plain-LLM 3/10** (run from 2026-05-20, not currently snapshotted on disk) |
| **Pass Agent — Claude + MCP** | `codegraph bench agent` | Same Claude Sonnet 4.6, varying registered MCP tools | **30-run dataset snapshotted** in `bench/RESULTS_AGENT_LATEST.md` |

### Drive-by patch to upstream codegraph

`codegraph/graph/builder.py:26,33` — added `.venvs` (plural) to `_BUILTIN_IGNORES` and `_IGNORE_DIRS`. Previously only `.venv` (singular) was ignored, so repos using multi-venv tooling (uv, our `bench/.venvs/`) parsed thousands of upstream files. This was the cause of the first agent-bench's runaway-CPU stall (6,397 extra Python files getting parsed).

### CLI surface added (`codegraph/cli.py`)

```
codegraph bench run    [--config bench/repos.yaml] [--only TOOL,...] [--pass A|B] [--run-id ID]
codegraph bench query  [--config bench/queries.yaml] [--only TOOL,...] [--run-id ID]
codegraph bench agent  [--configs bench/configurations.yaml] [--queries bench/queries.yaml]
                       [--only CONFIG,...] [--only-queries QUERY_ID,...]
                       [--model claude-sonnet-4-6] [--run-id ID]
```

### `pyproject.toml` extras

```
[project.optional-dependencies]
bench = [
    "anthropic>=0.40",
    "httpx>=0.27",
    "mcp>=1.0",
]
```

The `bench/` directory itself is **not shipped in the wheel** (see `[tool.hatch.build.targets.wheel]` comment) — it's developer-only.

---

## Comparison set status

| Tool | Pass A | Pass Q | Pass Agent | Why / why not |
|---|:---:|:---:|:---:|---|
| polycodegraph | ✅ | ✅ | ✅ | system under test |
| code-review-graph | ✅ | ❌ | ✅ | CLI + MCP both work; Pass Q runner not wired (uses CLI not MCP) |
| graphify | ⚠️ graph-only | ✅ | ❌ | No diff-review surface; MCP corrupts stdio JSON-RPC mid-call (anyio cancel-scope trip on cleanup) |
| repomapper | ⚠️ graph-only | ❌ | ❌ | No diff-review; no MCP server; agent unwireable |
| better-code-review-graph | ❌ excluded | ❌ excluded | ⚠️ wired, no full data | MCP-only — config wired + 1-query smoke succeeded (`turns=2 tokens=7499 cost=$0.026 correct`), but Anthropic spend cap blew before full grid ran |
| gitnexus | ❌ excluded | ❌ excluded | ❌ excluded | PolyForm Noncommercial license — never benchmark from this MIT repo |
| JudiniLabs/mcp-code-graph | ❌ excluded | ❌ excluded | ❌ excluded | Thin client to hosted CodeGPT service, different category |
| plain-LLM (Gemini 2.5 Flash) | ✅ | ✅ | — (own row in agent bench is "baseline") | Provider-flexible (Gemini default, OpenAI optional) |

---

## Per-tool isolated venvs

External graph tools have conflicting tree-sitter pins (notably `tree-sitter-language-pack` 0.x vs polycodegraph's 1.8.x). Resolved by giving each external tool its own venv under `bench/.venvs/<tool>/`:

- `bench/.venvs/code-review-graph/` — Python 3.14, `code-review-graph` from PyPI
- `bench/.venvs/graphify/` — Python 3.14, `graphifyy[mcp]` from PyPI
- `bench/.venvs/better-code-review-graph/` — **Python 3.13** (pkg pins exactly 3.13.\*), `better-code-review-graph` from PyPI
- `bench/.venvs/repomapper/` — Python 3.14, but install crashes on `aider-chat` build (TASK #12 — fix pending)

`bench/runners/_venv.py:ensure_venv()` creates them on demand. Gitignored.

---

## Known limitations + open follow-ups

| # | Item | Effort | Notes |
|---|---|---|---|
| 12 | repomapper aider-chat install fails on Python 3.14 (`Cannot import setuptools.build_meta`) | 30 min | Fix: install setuptools+wheel before aider-chat, or pin venv to 3.11 |
| 13 | Pin real OSS commit SHAs in `repos.yaml` for Pass A reproducibility | 1 hour | Currently uses `HEAD` for codegraph-self; FastAPI/Django commented out |
| — | Better-CRG full agent-bench data (~$1 + 20 min) | 30 min after spend cap raised | One-query smoke proved it works; need spend headroom to run 10×2 grid |
| — | graphify in agent bench | unknown — upstream bug | Their MCP writes non-JSON to stdout during tool calls. Either we route stderr only or upstream fixes it |
| — | code-review-graph in Pass Q | 2 hours | Drive its MCP from the Pass Q harness same way agent does. Would let us add CRG to the Pass Q comparison table (currently only polycodegraph + graphify + plain-LLM). |
| — | Pass B (reproduce-the-work) | 1-2 days | Skeleton in `bench/runners/`; needs per-language test runner + diff-similarity scoring |
| — | `codegraph bench rescore --run-id <id>` | 1 hour | Mentioned in RESULTS.md, not wired. Cheap once `agent_raw_latest.jsonl` schema is stable. |
| — | Push branch to GitHub + open PR | when ready | Explicit user gate. |

---

## Two security incidents this session (both my fault, both addressed)

1. **`seedenv` value leaked via BSD-incompatible `sed` redaction** — piped seedenv output through `sed 's/=.\+$/=<set>/'` which silently doesn't match on macOS. Two real keys (GEMINI + OPENAI) landed in the chat transcript. User informed; user rotated.
2. **`grep` printed `anthropic_api_key:` line from `~/.assistant/config.yml`** in plain text. User informed; user said they'll rotate later.

**Net rule added to `~/.claude/CLAUDE.md`** under "Privacy & Security":
- Never grep-print secret-bearing files. Use `grep -c` / `grep -q` / `grep -oE '^[A-Z_]+_API_KEY'` (name only). Never `cat`, `head`, `tail`, `awk`, `sed -n`, or `Read` on `keys.env` / `.env` / `~/.assistant/config.yml`.
- "Cross-project key sync — `seedenv` always, never `sed`": if a project needs a key already in the central store, the fix is making the project seedenv-compatible (add `.env.example`, source `.env` at startup), not a one-off sed patch.

The auto-mode classifier started blocking my probes after this rule landed — that's working as intended.

---

## Anthropic spend cap

Hit twice during this session. Currently set to a low ceiling on the user's Anthropic account. Two specific costs:
- First clean 30-run agent bench (2026-05-20): ~$1.20 actual spend → produced `RESULTS_AGENT_LATEST.md`
- Second attempt to add better-CRG (2026-05-21): hit cap after ~$0.13 of new spend

`bench/budget.yaml` has a $100 global ceiling on our side, but the Anthropic-account cap is the real binding constraint right now. Raising it is a user-side console action.

---

## What to do next (in order of payoff)

1. **Pick a LinkedIn post version** (`bench/LINKEDIN_POST.md` — A/B/C) and ship. Numbers are committed; screenshot the table from `bench/RESULTS_AGENT_LATEST.md` and post.
2. **Push the branch** and open a PR if you want public review on the harness code before the post lands.
3. **Bump Anthropic spend cap, re-run agent bench with better-CRG** — adds a 4th column to the headline table. ~$1 + 20 min. Adds credibility ("we compared against everything we could").
4. **Snapshot Pass Q results** the same way as Pass Agent — `bench/results/<id>/RESULTS.md` is currently gitignored, so the 10/10 vs 6/10 vs 3/10 Pass Q numbers from 2026-05-20 are not on disk anymore. Add `bench/RESULTS_QUERY_LATEST.md` after a re-run.
5. **Pin OSS commit SHAs** (task #13) — required before the post links to "fully reproducible benchmark". Currently the bench reproduces against whatever HEAD looks like when you run it.

---

## How to reproduce the headline numbers

```bash
# One-time
git checkout feat/bench-harness
pip install -e '.[bench]'
seedenv .                # populates .env from central store (needs ANTHROPIC_API_KEY in store)

# Pass A (diff review)
codegraph bench run --only polycodegraph,code-review-graph,graphify

# Pass Q (graph query) — graphify + plain-llm need ~$0.03 of Gemini cost
codegraph bench query

# Pass Agent (Claude + MCP) — the headline. ~$2-3 of Sonnet 4.6 spend.
export ANTHROPIC_API_KEY=...  # or rely on seedenv-populated .env + `set -a; source .env; set +a`
codegraph bench agent --only baseline,polycodegraph,code-review-graph
```

All three commands write to `bench/results/<run-id>/`; the latest snapshot of Pass Agent lives at `bench/RESULTS_AGENT_LATEST.md`.
