"""Stub base class for external-tool runners that aren't wired up yet.

Each concrete subclass sets `name` and `upstream_url`. The first PR that
brings a tool online replaces the NotImplementedError with the real
shell-out / SDK call.
"""
from __future__ import annotations

from bench.types import CommitTarget, PassAResult, PassBResult


class StubRunner:
    name: str = "stub"
    upstream_url: str = ""

    def review_diff(self, target: CommitTarget, budget_usd: float) -> PassAResult:
        raise NotImplementedError(
            f"{self.name} runner not yet wired — upstream: {self.upstream_url}. "
            f"See bench/runners/_stub.py for the adapter contract."
        )

    def reproduce_work(self, target: CommitTarget, budget_usd: float) -> PassBResult:
        raise NotImplementedError(
            f"{self.name} Pass B not yet wired — upstream: {self.upstream_url}"
        )
