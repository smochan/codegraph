# Attribution Research: Does codegraph descend from code-review-graph?

## 1. Verdict

**No.** `codegraph` is an independent green-field implementation. `code-review-graph` (tirth8205) appears in our internal docs only as a **competitor / peer**, never as an ancestor. The user is conflating "competitor" with "fork origin."

## 2. Evidence

- **First commit is a clean bootstrap, not a fork import.** `git log --reverse` first entry: `4ec1902 chore: bootstrap codegraph package (Phase 0)` — a normal scaffold commit, no large initial code drop typical of a fork. Sole remote is `https://github.com/smochan/codegraph.git`.
- **No attribution strings anywhere in source.** `grep -ri "code-review-graph\|forked\|based on"` against `README.md`, `codegraph/`, `docs/` returns zero hits referencing tirth8205's project. README mentions of "origin" are unrelated (CSS `transform-origin`, git `origin/HEAD`, import "original name").
- **Internal planning docs explicitly position it as a competitor.** `.planning/SESSION_HANDOFF.md`: *"The space is crowded — GitNexus … code-review-graph, JudiniLabs/mcp-code-graph, sdsrss/code-graph-mcp, RepoMapper, Graphify, colbymchenry/codegraph."* `.planning/MASTER_PLAN.md`: *"switching to embeddings (that's better-code-review-graph's lane)."* `.planning/draft_linkedin.md` shows a feature-comparison table treating it as a peer.
- **Architectural divergence.** code-review-graph stores in a knowledge-graph + embeddings model aimed at token-efficient AI review context. codegraph stores in a single SQLite relational store, ships a 3D flow tracer, decorator-aware dead-code detection, and a CLI/MCP/web triad — different design center, not a derived feature set.
- **Author and timing.** code-review-graph copyright is Tirth Kanani 2026; codegraph copyright is mochan 2026. Both are recent. No shared file headers or per-file copyright notices that would survive a fork.

## 3. License of code-review-graph

**MIT License**, copyright 2026 Tirth Kanani — https://github.com/tirth8205/code-review-graph/blob/main/LICENSE. (MIT-to-MIT would be compatible *if* a fork relationship existed; it does not.)

## 4. Other named projects' licenses

| Project | URL | License |
|---|---|---|
| code-review-graph (tirth8205) | github.com/tirth8205/code-review-graph | MIT |
| better-code-review-graph (n24q02m) | github.com/n24q02m/better-code-review-graph | MIT (fork of above) |
| GitNexus | (referenced in handoff) | not verified — out of scope; verify before any mention |
| JudiniLabs/mcp-code-graph | github.com/JudiniLabs/mcp-code-graph | not verified |
| sdsrss/code-graph-mcp | github.com/sdsrss/code-graph-mcp | not verified |
| RepoMapper / Graphify / colbymchenry/codegraph | various | not verified |

Only code-review-graph and better-code-review-graph were directly inspected; the rest are out of scope for this question and have no claim on us absent evidence of code reuse.

## 5. Proposed attribution paragraph (if user still wants one)

Not warranted. We owe **no MIT attribution** to code-review-graph because we did not copy or fork its code. Adding "built on top of code-review-graph" to our README would be **factually incorrect** and could mislead users into thinking we are a downstream of that project.

## 6. Alternative recommendation — "Prior Art" section

If the user wants to acknowledge the surrounding ecosystem honestly, add a short **Prior Art / Related Work** section near the bottom of `README.md` (after "What it does NOT do") rather than at the top. Suggested wording:

> ## Prior art and related projects
>
> codegraph was built independently. Other projects in the local code-graph / MCP-for-AI space worth knowing about: [code-review-graph](https://github.com/tirth8205/code-review-graph) and its fork [better-code-review-graph](https://github.com/n24q02m/better-code-review-graph) (token-efficient review context with embeddings), GitNexus, and JudiniLabs/mcp-code-graph. codegraph's wedge is decorator-aware dead-code detection, a 3D focus-mode flow tracer, and (in v0.2) cross-stack data-flow tracing — not embedding-based retrieval.

This frames us accurately, helps SEO, and avoids overclaiming.

## 7. Risks / caveats

- **Do not** add "built on top of code-review-graph" — that would be a false provenance claim.
- If any code *was* copy-pasted from code-review-graph and the user knows but I missed it, only the user can confirm. Nothing in the tree suggests this; first commit and file-by-file headers show original authorship.
- Verify GitNexus / Judini / sdsrss licenses before naming them in README, in case any uses GPL/AGPL — naming alone is fine, but ensure no later code reuse occurs without checking.
- The user's recollection ("we built on top of code-review-graph because that is open source") likely came from seeing it repeatedly in `.planning/SESSION_HANDOFF.md` and `.planning/draft_linkedin.md`. Worth a 30-second clarifying conversation before any README change.
