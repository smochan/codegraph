# Docs Audit — codegraph 0.1.0 pre-public-push

Date: 2026-04-26 · Auditor: research agent (audit-only, no code/doc changes)

## Source-of-truth snapshot (verified just now)

| Metric | Value | Source |
|---|---|---|
| Nodes | 2268 | `codegraph analyze` |
| Edges | 4963 (CALLS=3495, IMPORTS=634, DEFINED_IN=814, INHERITS=20) | `codegraph analyze` |
| Unresolved edges | 2746 | `codegraph analyze` |
| Dead code findings | **4** (not 3) | `codegraph analyze` |
| Cycles | **3** | `codegraph analyze` |
| Untested functions | 272 | `codegraph analyze` |
| pytest count | **273 passed** | `pytest -q` |
| node tests | 22 pass / 0 fail | `node --test` |
| Languages | python, typescript, tsx, javascript | analyze output |
| LICENSE file | **PRESENT** (MIT, 1063 bytes) | `ls LICENSE` |
| CHANGELOG status | "[0.1.0] - **UNRELEASED**" | head CHANGELOG.md |
| `docs/images/dashboard.png` | **MISSING** (whole `docs/images/` dir absent) | `ls` |
| PyPI `codegraph-py` | **404 — not published** | `pypi.org/pypi/codegraph-py/json` |
| `docs/plan.md` linked from README | exists | `ls` |

---

## 1. Severity-ranked punch list

| # | Sev | File | Current state | Required change | Source |
|---|---|---|---|---|---|
| 1 | CRITICAL | `README.md:19` | `![dashboard](docs/images/dashboard.png)` | Image file does not exist — broken on GitHub render. Add real screenshot or remove line. | `ls docs/images` → ENOENT |
| 2 | CRITICAL | `README.md:5,6,116` | PyPI badge + `pip install codegraph-py` quickstart | Package not on PyPI (404). Either publish first, OR replace with `pip install -e .` from clone + "PyPI: coming soon" note. Badge will render "not found". | curl pypi.org → 404 |
| 3 | CRITICAL | `README.md:79,187` | "147 to 202 passing tests" | Actual: **273 passed** (Python) + 22 (node). Update both spots. | `pytest -q` |
| 4 | CRITICAL | `README.md:73, 80-83` | "451 → 3 dead code", "Three [cycles] were found" | Dead code is **4** today (`_propagate_class_role_to_members`, `upsert_node`, `vacuum`, `_register.decorator`). Cycles still 3, narrative still works but the "2 accepted, 1 tracked" breakdown needs re-checking against the 3 cycles now reported (UI redraw, parser nested-defs, `mcp_server.run`). | `codegraph analyze` |
| 5 | CRITICAL | `CHANGELOG.md` | `## [0.1.0] - UNRELEASED` | Set release date or keep UNRELEASED but README claims "Status: 0.1.0 — ready for PyPI" — contradiction. | head CHANGELOG.md |
| 6 | HIGH | `README.md` (entire "What it does") | No mention of DF0 params/args, DF1.5 role classification, hover signature tooltips, role-grouped picker, legend, edge arg labels | Add bullets — these are the most recent shipped features (commits `94da0d3`, `5dcb6f6`, `9d65462`, `18701d5`, `393faca`). | git log |
| 7 | HIGH | `.planning/SESSION_HANDOFF.md` | Last updated for 4-merge launch sprint; HEAD listed as `f8bbd56`; pytest "147 passed". Does **not** mention DF0, DF1.5, role classification, hover-label fix (sprite labels failed → switched to native HTML hover), legend-render fix. | Rewrite "What landed" + numbers + manual-steps to match current HEAD `393faca`. | git log + pytest |
| 8 | HIGH | `.planning/draft_linkedin.md` | "147 to 202", "451 → 3", `pip install codegraph-py` | Update test count to 273; dead code 451 → 4; verify package install path; mention DF0/DF1.5/3D focus features if they're part of the 0.1.0 narrative. | analyze + pytest + pypi |
| 9 | HIGH | `README.md:60-64` "What it does NOT do" | OK on TS R2 / type inference / cross-stack | Add: argument data flow is **text-only, no type inference** (DF0 captures arg source text, not value flow); always-on labels deferred (only hover labels work without build step); service classification limited to HTTP frameworks (no Typer-style CLI roles). | implementation reality |
| 10 | HIGH | `README.md:94-104` comparison table | Missing **GitNexus** (28K-star competitor, named in SESSION_HANDOFF as the headline rival) | Add GitNexus row. Wedge phrasing in row labels is OK but explicitly state "external calls stop at boundary; decorator-aware" in the narrative below the table. | SESSION_HANDOFF.md |
| 11 | MEDIUM | `README.md` | No attribution section | Add credits: tree-sitter, vasturiano/3d-force-graph, networkx, pydantic, typer, rich, MCP SDK. `code-review-graph`: per `RESEARCH_ATTRIBUTION.md` it is NOT an ancestor — no attribution required, but a "prior art" note is optional. | RESEARCH_ATTRIBUTION.md |
| 12 | MEDIUM | `README.md:62-63` | "TS R2 deferred to v0.1.2" | Roadmap section §192 says "v0.1.1 — TS R2". Pick one. | self-conflict |
| 13 | MEDIUM | `docs/plan.md` | Linked from README §194 — content unverified, likely stale (pre-DF0/DF1.5 era) | Read + refresh, or remove the link if `MASTER_PLAN.md` is the new SOT. | not yet read |
| 14 | MEDIUM | `.planning/MASTER_PLAN.md` | Wave 1–4 marked done implicitly; nothing about DF0/DF1.5 work that landed afterward | Add a "Post-launch landed" section or supersede with a v0.1.0-shipped doc. | git log |
| 15 | MEDIUM | `.planning/PLAN_DATAFLOW.md` | Treats DF1–DF4 as v0.2 wedge | DF0 (params/args) and DF1.5 (roles) have shipped. Update headers so future readers see what's done vs pending (DF1–DF4 still v0.2). | git log |
| 16 | LOW | README "Languages today" | "Python and TypeScript / JavaScript" | Accurate (analyze confirms python/typescript/tsx/javascript present). Keep. | analyze |
| 17 | LOW | `docs/HANDOFF.md`, `docs/TODO_FOR_YOU.md`, `docs/LINKEDIN_POST.md` | Pre-launch artifacts now stale | Either move to `.planning/archive/` or delete before public push so casual readers don't hit them. | ls docs |
| 18 | LOW | README badges line 7 | `Status: 0.1.0` static badge | Fine, but if not yet released, set to `0.1.0-pre`. | self-consistency |

---

## 2. Net new files needed

- `docs/images/dashboard.png` — real screenshot (referenced from README:19, currently broken).
- Optional: `docs/CONTRIBUTING.md` for a public push (not strictly required).
- LICENSE: **already present**, no action.

---

## 3. Corrected metrics — single source of truth

Every doc going forward should use exactly these:

| Claim | Correct value |
|---|---|
| Dead code (self-graph) | **451 → 4** (not 3) |
| Cycles (self-graph) | **3** (1 UI redraw loop, 1 parser self-recursion via `_visit_nested_defs`, 1 MCP `_serve↔run`) |
| Python tests | **273 passed** |
| JS/node tests | **22 passed** (graph3d_focus + graph3d_transform) |
| Resolver categories fixed | **5** (per-name imports, relative imports, same-file ctor calls, nested-call attribution + decorator-call edges, class-annotation `self.X.Y` chains, fresh-instance method calls) — phrase as "5+ categories" since the list above has 6 |
| Framework decorators recognized | **24** |
| Languages | Python, TypeScript, JSX/TSX, JavaScript |
| Nodes / Edges (self-graph) | 2268 / 4963 |
| MCP tools | **10** (find_symbol, callers, callees, blast_radius, subgraph, dead_code, cycles, untested, hotspots, metrics) |
| 3D view features | focus-mode flow tracer, role-grouped picker (HANDLER/SERVICE/COMPONENT/REPO), color+kind legend, hover signature tooltip, edge-arg labels, expand/collapse, external-leaf treatment |

---

## 4. Suggested README outline (structural changes)

Current is mostly fine; add two sections + tighten:

1. Header + badges (fix PyPI/status)
2. One-line pitch + screenshot (fix broken image)
3. **What it does** (add: param capture, role classification, hover signatures, edge arg labels)
4. **What it does NOT do yet** (add the three caveats from #9 above)
5. **Honest engineering** (correct numbers per §3)
6. **Where it fits** comparison table (add GitNexus row)
7. Quickstart (fix install)
8. Commands
9. MCP / Claude Code usage
10. Development
11. **Acknowledgements** (NEW — tree-sitter, 3d-force-graph, networkx, pydantic, typer, rich, MCP SDK)
12. Roadmap (sync v0.1.1/v0.1.2 wording)
13. License

---

## 5. Estimated edit time

| Bucket | Hours |
|---|---|
| README rewrite (numbers, missing features, attribution, install, image) | 1.5 |
| Capture + add `docs/images/dashboard.png` | 0.5 |
| `SESSION_HANDOFF.md` rewrite | 0.5 |
| `draft_linkedin.md` numbers + features refresh | 0.3 |
| `CHANGELOG.md` finalize 0.1.0 entry + date | 0.3 |
| `MASTER_PLAN.md` + `PLAN_DATAFLOW.md` "what shipped" notes | 0.4 |
| Stale `docs/*.md` cleanup (HANDOFF/TODO/LINKEDIN_POST) | 0.2 |
| Cross-doc consistency pass | 0.3 |
| **Total** | **~4 hours** |

