# PLAN — v0.3 Unified Trace

**Sprint:** v0.3 unified trace
**Owner:** TBA
**Status:** Spec
**Estimated effort:** 5–7 days
**Sibling docs:** [`PLAN_DATAFLOW.md`](./PLAN_DATAFLOW.md), [`SESSION_HANDOFF.md`](./SESSION_HANDOFF.md)

---

## 1. Why

Two valuable features shipped on `main` this week, but they don't talk to each
other. Closing that gap is the single highest-leverage UI moment in the product.

### What users see today

- `codegraph dataflow trace "GET /api/users/{id}"` returns a text / JSON
  `DataFlow`: an ordered list of hops from the frontend `FETCH_CALL` through
  the handler, services, repositories, down to the SQL read / write target.
  Useful, but **terminal-only**.

- The Architecture view's Learn Mode modal (PR #15) animates the full request
  lifecycle as either a sequence diagram or a pipeline view:

  | Phase | Content                                              | Project-specific? |
  |-------|------------------------------------------------------|-------------------|
  | 1     | TCP handshake (SYN / SYN-ACK / ACK)                  | No (generic)      |
  | 2     | TLS handshake (ClientHello / ServerHello / Finished) | No (generic)      |
  | 3     | HTTP request (method, path, headers)                 | Partial — uses real handler/path |
  | **4** | **Project-specific data layer**                      | **No — generic placeholder** |
  | 5     | Response (status, body shape)                        | Partial           |

  Phase 4 is the one that's supposed to be project-specific, and today it's
  the most generic phase in the modal — a pretty animation with no actual
  link to the user's repo.

### What we want

- Click an endpoint in Architecture view → Learn Mode → **Phase 4 renders the
  real `DataFlow` for that handler**, with each hop annotated by DF0 args /
  kwargs and DF1.5 role.
- The same data the CLI emits, but visualised as the connected lifecycle the
  Learn Mode modal already teaches.
- Stretch: **argument-flow propagation.** Highlight `user_id` (or the
  user-selected param) as a single coloured token that travels from the fetch
  body → route param → service arg → repo arg → DB query placeholder. This
  is what closes the "what does this value become?" gap that DF0 + DF4 hint
  at but don't yet show end-to-end.

This is the moment that sells the product. Everything else is supporting
infrastructure.

---

## 2. Architecture

```text
┌──────────────────────┐         ┌──────────────────────┐
│  Architecture view   │  click  │   /hld payload       │
│  (handler list)      │ ──────▶ │   (existing)         │
└──────────────────────┘         └──────────────────────┘
            │                              │
            │ openLearnModal(handler)      │ + dataflow per handler
            ▼                              ▼
┌──────────────────────┐         ┌──────────────────────┐
│  Learn Mode modal    │ ◀────── │   /hld?include=df4   │
│  (Phase 4 wiring)    │         │   (NEW field)        │
└──────────────────────┘         └──────────────────────┘
            │                              ▲
            │ render hops                  │ joins on handler_qn
            ▼                              │
┌──────────────────────┐         ┌──────────────────────┐
│  Phase 4 sequence    │         │ analysis.dataflow    │
│  diagram (per hop)   │         │ .trace() per handler │
└──────────────────────┘         └──────────────────────┘
```

### Component responsibilities

| Layer       | File                                          | Change                                  |
|-------------|-----------------------------------------------|-----------------------------------------|
| Backend     | `codegraph/viz/hld.py`                        | Add per-handler `dataflow` field        |
| Backend     | `codegraph/analysis/infrastructure.py`        | Return DF4 trace alongside handler list |
| Backend     | `codegraph/analysis/dataflow.py`              | Reused as-is — already exposes `trace()`|
| Frontend    | `codegraph/web/static/views/architecture.js`  | Wire Phase 4 to render real hops        |
| API         | `codegraph/web/server.py` (HLD endpoint)      | Optional `?include=dataflow` param      |

### Data shape (proposed)

```jsonc
// per handler in HLD payload
{
  "qualname": "app.api.users.get_user",
  "method": "GET",
  "path": "/api/users/{id}",
  "role": "HANDLER",
  "framework": "fastapi",
  "dataflow": {
    "hops": [
      { "kind": "FETCH_CALL", "qualname": "src/UserCard.tsx::fetchUser",
        "args": ["userId"], "body_keys": [] },
      { "kind": "ROUTE",      "qualname": "app.api.users.get_user",
        "args": ["id"], "role": "HANDLER" },
      { "kind": "CALL",       "qualname": "app.services.user.UserService.get",
        "args": ["user_id"], "role": "SERVICE" },
      { "kind": "CALL",       "qualname": "app.repos.user.UserRepo.find_by_id",
        "args": ["user_id"], "role": "REPO" },
      { "kind": "READS_FROM", "qualname": "app.models.User",
        "args": ["user_id"], "role": null }
    ],
    "confidence": 0.92
  }
}
```

---

## 3. Concrete code touch points (estimated)

### Backend (~2 days)

- **`codegraph/viz/hld.py`** — extend the per-handler dict with a `dataflow`
  field by calling `analysis.dataflow.trace(handler_qn)` for each handler in
  the route table. Gate behind `?include=dataflow` so existing HLD consumers
  don't pay the cost.
- **`codegraph/analysis/infrastructure.py`** — already returns the handler
  list. Wire the same `dataflow.trace()` call into `detect_infrastructure()`
  output, or join it in the viz layer. Prefer the viz layer (keep analysis
  pure).
- **`codegraph/analysis/dataflow.py`** — already exposes `trace()`. May need
  one new helper that returns the raw hop list (without `DataFlow` envelope)
  so the viz layer doesn't have to unwrap.
- **Tests** — new `tests/test_hld_dataflow.py` confirming the HLD payload
  contains a `dataflow.hops` array for each `HANDLER` node.

### Frontend (~2–3 days)

- **`codegraph/web/static/views/architecture.js`** — locate the Phase 4
  block (around line 303, `// ---- Phase 4: Project-specific data layer`).
  Replace the generic animation with:
  - One swimlane per role (`HANDLER`, `SERVICE`, `REPO`, `DB`).
  - One arrow per hop, labelled with the call args (DF0 text).
  - Click a hop → opens the source file at the call site (uses existing
    `jumpToQualname` plumbing).
- **`drawLearnSequence`** — already renders sequence-style; extend to accept
  a `dataflow.hops` array as input rather than the static stages list.
- **`drawLearnPipeline`** — likewise, extend to render hops as pipeline
  segments.
- **Tests** — new `tests/test_architecture_phase4.js` (Node `--test` style,
  consistent with existing JS tests). Mock the HLD payload, assert the modal
  renders the right number of swimlanes and the right hop labels.

### Stretch — argument-flow propagation (~1–2 days)

- **`codegraph/analysis/dataflow.py`** — add a per-hop `arg_flow` field
  mapping a frontend body key to its name in each hop's local scope. Pure
  text matching today; full identity tracking is out of scope (deferred to
  v0.4).
- **Frontend** — render the selected param as a coloured token that follows
  the user's pointer along the swimlane. CSS-only animation — no rAF loop.

---

## 4. Out of scope (defer to v0.4)

- **Cross-process traces** — service A in repo X calls service B in repo Y.
  Requires linking multiple `.codegraph/graph.db` files; not a one-repo
  feature.
- **Async / await flow** — `asyncio.gather`, fire-and-forget tasks, message
  queue side effects. Today's DF4 walks the synchronous call graph only.
- **Error-path branches** — `try` / `except`, fallback handlers, retry
  middleware. Lifecycle modal currently shows the happy path; error paths
  would need a separate visualisation mode.
- **Real-time DB query plans.** We render the SQL target *node*; we do not
  call `EXPLAIN`.
- **Authentication middleware as a first-class hop.** Today auth shows up
  as a regular CALL in the chain. Surfacing it as a distinct "auth phase"
  is a v0.4 polish item.

---

## 5. Effort estimate

| Block                              | Days |
|------------------------------------|------|
| Backend: HLD payload + analysis    | 2    |
| Frontend: Phase 4 wiring + tests   | 2–3  |
| Stretch: argument-flow propagation | 1–2  |
| Buffer (review, polish, demo)      | 0.5  |
| **Total**                          | **5–7 days** |

Single contributor, full-time. Multi-contributor parallelism is possible
(backend + frontend split) but adds coordination overhead — recommend
single-track for this sprint.

---

## 6. Acceptance criteria

The sprint is **done** when:

1. Clicking any endpoint in the Architecture view → Learn Mode → Phase 4
   shows the **real** chain for that endpoint:
   - Function names from the analyzed repo
   - File paths + line numbers (clickable)
   - DF0 argument values at each call site
   - DF1.5 role per hop
2. The output matches what `codegraph dataflow trace "<METHOD> <path>"`
   prints on the CLI — single source of truth.
3. The modal still works for repos *without* DF1 / DF4 data: Phase 4 falls
   back to today's generic animation with a "no trace data — run
   `codegraph build` first" hint.
4. Phase 4 stays under 200 KB of additional JS and renders in <100 ms on
   the codegraph self-graph.
5. New regression tests pass:
   - `tests/test_hld_dataflow.py` (Python)
   - `tests/test_architecture_phase4.js` (Node `--test`)
6. `pytest -q` stays green; total count grows to ~495.
7. `ruff check .` and `mypy --strict codegraph` clean.
8. Demo recorded against `examples/cross-stack-demo/`: click `/api/users/{id}`
   → modal opens → Phase 4 shows `fetchUser → get_user → UserService.get →
   UserRepo.find_by_id → User`. This recording becomes the LinkedIn
   launch-post hero.

---

## 7. Ship vs defer

| Feature                                   | Ship (v0.3) | Defer |
|-------------------------------------------|:-----------:|:-----:|
| Phase 4 wired to real DF4 hops            | ✅          |       |
| Per-hop role + DF0 args displayed         | ✅          |       |
| Click-through to source file              | ✅          |       |
| Sequence + Pipeline rendering parity      | ✅          |       |
| HLD `?include=dataflow` API               | ✅          |       |
| Graceful fallback when no DF4 data        | ✅          |       |
| Argument-flow propagation (single param)  | ✅ stretch  |       |
| Multi-param simultaneous propagation      |             | v0.4  |
| Cross-process traces (multi-repo)         |             | v0.4  |
| Async / await visualisation               |             | v0.4  |
| Error-path branch rendering               |             | v0.4  |
| Auth middleware as distinct phase         |             | v0.4  |
| `EXPLAIN`-driven query-plan annotation    |             | v0.4+ |

The minimum viable ship is rows 1–6: that alone takes us from "two
disconnected features" to "the single best onboarding moment in the
product." Stretch row 7 is the LinkedIn-launch hero shot — recommend
including it unless time pressure forces a cut.
