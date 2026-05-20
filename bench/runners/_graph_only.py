"""Adapter for tools that build a code graph but have no diff-review surface.

Pass A still wants a row for these tools — readers care about how long
graph construction takes vs polycodegraph. So we run the build, measure
setup time, and report zero findings + an explicit capability note in raw.
"""
from __future__ import annotations

import shutil
import subprocess
import time
from pathlib import Path

from bench.types import (
    CommitTarget,
    PassAResult,
    PassBResult,
    RunMetrics,
)


class GraphOnlyRunner:
    """Subclass and set `name`, `build_argv()`, and (optionally) `clean_dirs`."""
    name: str = ""
    upstream_url: str = ""
    clean_dirs: tuple[str, ...] = ()

    def build_argv(self, target: CommitTarget) -> list[str]:
        raise NotImplementedError

    def review_diff(self, target: CommitTarget, budget_usd: float) -> PassAResult:
        repo = target.repo_path
        branch = self._git(repo, "symbolic-ref", "--quiet", "--short", "HEAD").strip()
        original_head = branch or self._git(repo, "rev-parse", "HEAD").strip()
        setup_start = time.monotonic()
        try:
            self._git(repo, "checkout", "--detach", target.commit_sha)
            subprocess.run(
                self.build_argv(target),
                cwd=str(repo), check=False, capture_output=True, text=True,
            )
            setup_seconds = time.monotonic() - setup_start
            return PassAResult(
                tool=self.name,
                repo=target.repo_name,
                commit_sha=target.commit_sha,
                findings=[],  # tool has no review surface
                metrics=RunMetrics(
                    setup_seconds=round(setup_seconds, 3),
                    task_seconds=0.0,
                    failed=False,
                    failure_reason=(
                        f"graph-only: {self.name} has no diff-review surface; "
                        f"setup time measured for capability comparison"
                    ),
                ),
            )
        finally:
            self._git(repo, "checkout", original_head)
            for rel in self.clean_dirs:
                p = repo / rel
                if p.exists():
                    shutil.rmtree(p, ignore_errors=True)

    def reproduce_work(self, target: CommitTarget, budget_usd: float) -> PassBResult:
        raise NotImplementedError(
            f"{self.name} has no generation surface"
        )

    @staticmethod
    def _git(repo: Path, *args: str) -> str:
        return subprocess.run(
            ["git", "-C", str(repo), *args],
            check=False, capture_output=True, text=True,
        ).stdout
