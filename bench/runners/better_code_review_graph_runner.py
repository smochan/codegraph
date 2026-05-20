from __future__ import annotations

from bench.runners._excluded import ExcludedRunner


class BetterCodeReviewGraphRunner(ExcludedRunner):
    name = "better-code-review-graph"
    upstream_url = "https://github.com/n24q02m/better-code-review-graph"
    reason = (
        "MCP-only surface (no standalone CLI review). Driving it requires an "
        "MCP stdio client wrapper, which is non-trivial. Deferred to v2 of the "
        "benchmark. Capability is real — wiring is the cost."
    )
