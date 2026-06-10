# Codegraph vs. an LLM Code-Reviewer — Gap Analysis & Build Plan

**Purpose:** make `codegraph review` catch the classes of issue that an LLM reviewer caught on a
real PR (the `cockpit` autopilot feature) but that codegraph currently misses. Every gap below is
mapped to a concrete capability, the exact codegraph module that would own it, and the graph-schema
or rule-engine change required.

**Method:** an LLM `code-reviewer` agent reviewed the `feat/autopilot` branch twice (before and after
the first round of fixes). Its findings were cross-referenced against a source-level inventory of
codegraph (`codegraph/review/*`, `codegraph/analysis/*`, `codegraph/graph/schema.py`,
`codegraph/parsers/*`). Nothing here is speculative about codegraph's current behavior — capability
claims cite the file that implements (or fails to implement) them.

---

## 1. What codegraph detects today (baseline)

Grounded in source:

| Capability | Module | Mechanism |
|---|---|---|
| Dead code | `analysis/dead_code.py` | zero incoming CALLS/IMPORTS/INHERITS/IMPLEMENTS edges |
| Untested functions | `analysis/untested.py` | zero incoming CALLS **from a test module** |
| Import/call cycles | `analysis/cycles.py` | SCCs over IMPORTS-only and CALLS-only subgraphs |
| Hotspots | `analysis/hotspots.py` | `fan_in*2 + fan_out + LOC/50` |
| Metrics | `analysis/metrics.py` | node/edge counts by kind + language |
| PR diff review | `review/differ.py` | node/edge add/remove/modify between baseline and HEAD |
| Risk scoring | `review/risk.py` | fan-in, removed-but-referenced, hotspot, cycle, signature change |
| Rule engine | `review/rules.py` | YAML rules over 7 triggers (see below) |
| Cross-layer dataflow | `analysis/dataflow.py` | DF4: CALLS + FETCH_CALL→ROUTE + READS_FROM/WRITES_TO, depth ≤ 6 |

**Rule triggers that exist** (`review/rules.py`): `added_node`, `removed_node`, `modified_node`,
`removed_referenced`, `introduces_cycle`, `high_fan_in`, `new_dead_code`.

**Graph schema** (`graph/schema.py`):
- Node kinds: FILE, MODULE, CLASS, FUNCTION, METHOD, VARIABLE, PARAMETER, IMPORT, TEST
- Edge kinds: DEFINED_IN, IMPORTS, CALLS, INHERITS, IMPLEMENTS, READS, WRITES, RETURNS, PARAM_OF,
  TESTED_BY, ROUTE, READS_FROM, WRITES_TO, FETCH_CALL

The decisive limitation: **codegraph reasons about the call/import/diff graph, not about values
flowing through code.** Every gap below is a consequence of that one fact, plus the absence of a
syntactic (AST-level) lint pass.

---

## 2. The findings, mapped

Each row is a real finding from the LLM review. "Detectable today?" is about codegraph as it ships now.

| # | Finding (from the LLM review) | Class | Detectable by codegraph today? | Why / why not |
|---|---|---|---|---|
| 1 | Scraped/AI-extracted URL flows into `page.goto`/`fetch` with no SSRF guard | **Taint: untrusted source → network sink** | No | No taint tracking; no source/sink catalog |
| 2 | `frameSrc` (iframe `src`) navigated without validation | Taint (same class) | No | Same |
| 3 | Auto-pick query re-fills jobs in any status (data-integrity) | **DB query semantics / missing filter** | Partial | Graph sees the `db.select` call; can't see the missing `.where` |
| 4 | Status write regresses `applied`→`prepared` (no state-machine guard) | **Domain state machine** | No | Requires declared state model; pure semantics |
| 5 | Demographics (gender/ethnicity/...) hardcoded in a source constant | **Sensitive literal in source** | No | No literal/secret scanning |
| 6 | Hardcoded scoring stack in an AI prompt (non-configurable) | Config-not-externalized | No | Same family as #5 |
| 7 | `launchSharedChromium` race: module-global flag + `await` between check & set | **Concurrency / shared mutable state** | No | No await-ordering or shared-state analysis |
| 8 | N+1: `SELECT` then `INSERT` per item inside a scan loop | **DB-call-in-loop** | No | Graph has the call edge but not the enclosing loop |
| 9 | Full-table scan: `db.select().from(jobs)` with no `WHERE` in a hot path | **Query shape** | No | Needs query-builder chain analysis |
| 10 | `consultPreference` full-scans the table on every field | DB-call-in-loop + hot path | Partial | `callers`/hotspots hint at frequency; can't see the query |
| 11 | Route reads `req.json()` and uses it without Zod `.parse` | **Taint: request body → use without validation** | No | No taint; no "validated" sink concept |
| 12 | Critical autopilot functions are untested | Coverage | **Yes** (`untested`) | But not risk-ranked |
| 13 | `console.log`/`console.error` in production server code | **Syntactic lint** | No | No AST lint pass |
| 14 | `any` types on DB writes weaken safety | **Type quality** | No | Graph is type-agnostic |
| 15 | SSRF allowlist omits CGNAT `100.64.0.0/10` | Rule-config completeness | No | Requires understanding the allowlist's intent |
| 16 | Bespoke test harness not wired into the runner | Convention/config | No | Out of graph scope |

Codegraph catches **1 of 16** today (untested, un-ranked). The rest cluster into five buildable
capabilities.

---

## 3. The five capabilities to build

Ordered by leverage (how many findings each unlocks) and by how well it fits codegraph's existing
architecture.

### Capability A — Taint analysis (source → sink)  ⭐ highest leverage

**Unlocks:** #1, #2, #11 (SSRF, iframe-nav, missing-validation) — and generalizes to SQL/command
injection, XSS, secret-exfiltration, path traversal. This is the single biggest gap and the one most
aligned with codegraph's graph-first design.

**What it is:** track whether a value originating from an *untrusted source* reaches a *dangerous
sink* without passing through a *sanitizer*. Codegraph already has the call graph and the
FETCH_CALL/ROUTE/READS_FROM/WRITES_TO edges — taint is the natural next layer on top.

**What to build:**

1. **A source/sink/sanitizer catalog** — `codegraph/analysis/taint_catalog.py` (YAML-backed, like
   `review/rules.py`). Entries are matched against callee qualname / parameter origin:
   - *Sources* (untrusted): HTTP request body/params/query (route-handler params reachable from a
     ROUTE edge), `fetch`/HTTP response bodies, file reads, scraped DOM text, **LLM/AI output**,
     env-derived user content.
   - *Sinks* (dangerous): `fetch`, `page.goto`, `page.setInputFiles`, `child_process.exec`,
     `db.execute`/raw SQL, `eval`, `dangerouslySetInnerHTML`, file-path joins.
   - *Sanitizers*: functions whose return "clears" taint for a sink class — e.g. `isSafePublicUrl`
     for the network-sink class, a Zod `.parse`/`.safeParse` for the validation class, an HTML
     escaper for the DOM class. **This is what lets the tool see that the *fixed* cockpit code is
     now safe** (the guard call on the path), not just that a source reaches a sink.

2. **Variable-level dataflow edges** — the hard part. Today `dataflow.py` is call/route-level only.
   Add intra-procedural def-use tracking in the parsers (the tree-sitter ASTs in
   `parsers/typescript.py` and `parsers/python.py` already have assignment/return/param nodes — they
   are just dropped). Emit new edges:
   - `DATA_ASSIGN` (rhs value → lhs variable)
   - `DATA_ARG` (variable → the parameter slot of a call)
   - `DATA_RETURN` (return expression → call-site result)
   Inter-procedural propagation then reuses existing CALLS edges: taint on an argument flows to the
   callee's PARAMETER node; taint on a `return` flows back to the caller's result variable.

3. **A taint propagation pass** — `codegraph/analysis/taint.py`: worklist over the new data edges +
   CALLS edges, seeded at sources, absorbed at sanitizers, reported at sinks. Bound it (depth cap,
   like DF4's `max_depth=6`) to stay tractable. Report each finding as a *witness path*
   source→…→sink so the PR comment can show the flow (this is exactly what makes the SSRF finding
   actionable).

4. **New rule triggers** in `review/rules.py`: `taint_reaches_sink` (with `source_class` /
   `sink_class` / `sanitizer` match fields). Severity from the sink class (network=high, sql=critical,
   eval=critical).

**Precision note (be honest in the docs):** start **intra-procedural + one level of
inter-procedural** (args/returns across a single CALLS hop). That already catches #1/#2/#11. Full
flow-sensitive, field-sensitive taint is a research project — don't promise it. Report confidence
(like `match_route`'s 0.5–1.0 scoring in `dataflow.py`) and let `--fail-on` gate on high-confidence
only.

---

### Capability B — Syntactic lint pass (AST rules)  ⭐ second-highest leverage

**Unlocks:** #8, #9, #10 (N+1 / DB-call-in-loop / full-table-scan), #13 (console.log), #5/#6
(hardcoded secrets & sensitive literals), partially #15.

**What it is:** a rule pass that runs over the *parsed AST*, not the graph. Codegraph already parses
every file with tree-sitter (`parsers/typescript.py`, `parsers/python.py`, `parsers/go.py`) and then
*discards* most syntactic structure when it builds the graph. A lint pass reuses those ASTs.

**What to build:**

1. `codegraph/analysis/lint.py` + a `codegraph/lint_rules/` catalog (YAML or small Python predicates).
   Each rule is `(node_pattern, context_predicate, severity, message)`.

2. Seed rules mapped directly to the findings:
   - **db-call-in-loop** (#8, #10): a call matching a DB-API pattern (`db.select`, `db.insert`,
     `.where`, `db.query`) whose AST ancestor chain contains a `for`/`while`/`.map`/`.forEach`.
     This needs the parser to retain *enclosing-loop* info — add a lightweight `in_loop` flag /
     `loop_depth` to call records during parse (cheap; the AST walk already visits loop nodes).
   - **unfiltered-query** (#9): a query-builder chain (`db.select().from(X)`) with no `.where`/
     `.limit` before it is awaited/returned. Pure AST chain inspection.
   - **console-in-prod** (#13): `console.*` calls in non-test files. Trivial; ship first as the
     "hello world" of the lint pass.
   - **sensitive-literal** (#5, #6): string/object literals assigned to identifiers matching
     `gender|ethnicity|race|veteran|disability|password|secret|api[_-]?key|token`, or high-entropy
     string literals. Heuristic, medium severity, low false-positive if scoped to assignment targets.

3. Wire the lint findings into the same `review` output path (`cli.py` review renderers already do
   markdown/JSON/SARIF) so they appear in the PR comment alongside graph-diff findings. Tag them
   `kind: lint` so they can be filtered.

**Why AST not graph:** these are *local* properties (a call's syntactic neighbourhood), not
*relational* ones. Trying to express "call inside a loop" in the current node/edge graph would require
loop nodes the schema doesn't have. A lint pass is the right tool and is independently useful.

---

### Capability C — Risk-ranked coverage & hot-path query cost

**Unlocks:** #12 (rank untested by criticality), reinforces #10.

Codegraph already computes `untested` and `hotspots` separately. Combine them:

- In `analysis/untested.py`, join each untested function to its hotspot score and blast-radius
  (`analysis/blast_radius.py`) so the report leads with *untested **and** high-fan-in* functions —
  which is exactly the autopilot-core case the LLM flagged. Pure composition of existing signals; no
  new graph data.
- Add a `review` trigger `new_untested_hotspot`: a newly-added FUNCTION/METHOD with fan-in ≥ threshold
  and zero TESTED_BY edge → HIGH. This turns coverage from a passive report into a PR gate.

---

### Capability D — Concurrency / shared-mutable-state heuristic

**Unlocks:** #7 (the browser-launch race).

Hardest of the "buildable" set, but a *narrow heuristic* covers the common real bug:

- Flag a **module-level mutable binding** (`let`/`var` at module scope, or a mutable module-global in
  Python) that is **read in a guard and written after an `await`** within the same async function —
  the classic check-then-act-across-await race. This needs: (a) module-scope mutable var detection
  (parser already sees top-level `let`), (b) per-async-function ordering of read/await/write on that
  var (AST walk). Report as MEDIUM with the advice "use a single in-flight Promise / mutex."
- Do **not** attempt general data-race detection. Scope it to this pattern and say so.

---

### Capability E — Type-quality signals (TS/Python)

**Unlocks:** #14 (`any` on DB writes), partially #4.

Tree-sitter gives syntactic types for free; codegraph just ignores them.

- During TS parse, record when a PARAMETER/VARIABLE/RETURN has type `any` (or is untyped where a
  type is expected). Add a lint rule **any-on-boundary**: `any` on an exported function signature or
  on a value passed to a DB write call → LOW/MEDIUM. Cheap, syntactic.
- This does **not** give real type inference (the inventory's #16 limitation stands) — it's a
  surface-syntax signal only. Be explicit about that.

---

## 4. What should stay the LLM's job (don't over-promise)

Honesty matters for the tool's credibility — these findings are genuinely out of reach for static
analysis and should be left to the LLM reviewer (or to human review):

- **#4 status regression** — requires knowing the *intended* job-status state machine. Static
  analysis can't infer that `applied → prepared` is "backwards" without a declared model. *Partial
  mitigation:* let users declare a state machine in `.codegraph/` (allowed transitions per field);
  then a write that sets a "lower" state becomes a rule. That's a real feature, but it's
  config-driven, not inference. Flag it as such.
- **#15 CGNAT gap in the allowlist** — judging the *completeness* of a security allowlist is
  semantic reasoning about intent. Taint analysis (Cap A) will tell you a guard *exists* on the path;
  it cannot tell you the guard is *missing a range*.
- **#16 test-harness-not-in-runner**, business-logic correctness, naming, comment accuracy — outside
  the graph entirely.

The goal isn't to replace the LLM reviewer; it's to make codegraph catch the **deterministic,
mechanical** classes (taint flows, query shapes, lint, coverage gaps) cheaply and with zero
false-negative drift, so the LLM's budget is spent on genuine semantics.

---

## 5. Roadmap (build order)

| Phase | Build | Findings unlocked | Effort | New schema? |
|---|---|---|---|---|
| **1** | **Lint pass** (Cap B): `analysis/lint.py` + console-in-prod, unfiltered-query, db-call-in-loop, sensitive-literal | #5, #6, #8, #9, #10, #13 | Low–Med | none (reuses ASTs) |
| **2** | **Coverage ranking** (Cap C): join untested×hotspot×blast-radius; `new_untested_hotspot` rule | #12 | Low | none |
| **3** | **Type-quality** (Cap E): `any`-on-boundary lint | #14 | Low | record `any` in parse |
| **4** | **Taint** (Cap A): data edges + source/sink/sanitizer catalog + propagation pass + `taint_reaches_sink` rule | #1, #2, #11 (+ injection/XSS broadly) | **High** | DATA_ASSIGN / DATA_ARG / DATA_RETURN edges |
| **5** | **Concurrency heuristic** (Cap D): check-then-act-across-await | #7 | Med | none |
| **6** | **State-machine rules** (opt-in config) | #4 (partial) | Med | declared transitions in `.codegraph/` |

Phases 1–3 are quick wins that reuse existing parse/graph data and ship value immediately. Phase 4
(taint) is the flagship — it's where codegraph stops being "a smarter dead-code/cycle tool" and
becomes a security-aware reviewer. Do 1–3 first to build the lint/rule plumbing that Phase 4 also
needs.

---

## 6. Concrete first PR (suggested)

Smallest end-to-end slice that proves the architecture:

1. Add `codegraph/analysis/lint.py` with one rule: **console-in-prod**.
2. Add a `lint_rules/default.yml` loaded the same way `review/rules.py` loads `DEFAULT_RULES`.
3. Surface lint findings through the existing `review` renderers (`cli.py`), tagged `kind: lint`,
   honoring `--fail-on`.
4. Add a fixture repo with one `console.log` in a non-test file; assert it's flagged and that a
   `console.log` in a `*.test.ts` is not.

That establishes the lint pass + rule-loading + output + severity-gating plumbing that every later
phase reuses, with a rule that has near-zero false positives. Then layer `unfiltered-query` and
`db-call-in-loop` onto the same pass, and you've already covered 5 of the 16 findings.

---

*Generated from a source-level audit of codegraph and a two-pass LLM review of `cockpit@feat/autopilot`.
Capability claims cite the implementing module; gaps cite the absence. Update this doc as phases land.*
