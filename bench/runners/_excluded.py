"""Adapter for tools deliberately excluded from v1 with a documented reason.

The harness still emits a row for these tools so RESULTS.md is honest about
the comparison set — no silent omissions.
"""
from __future__ import annotations

from bench.types import (
    CommitTarget,
    PassAResult,
    PassBResult,
    RunMetrics,
)


class ExcludedRunner:
    name: str = ""
    upstream_url: str = ""
    reason: str = ""

    def review_diff(self, target: CommitTarget, budget_usd: float) -> PassAResult:
        return PassAResult(
            tool=self.name,
            repo=target.repo_name,
            commit_sha=target.commit_sha,
            findings=[],
            metrics=RunMetrics(
                failed=True,
                failure_reason=f"excluded-v1: {self.reason}",
            ),
        )

    def reproduce_work(self, target: CommitTarget, budget_usd: float) -> PassBResult:
        raise NotImplementedError(self.reason)
