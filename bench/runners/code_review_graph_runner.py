"""code-review-graph adapter — drives the upstream CLI via an isolated venv.

Upstream: https://github.com/tirth8205/code-review-graph (MIT, Python, PyPI).

Flow per task:
  1. git checkout commit_sha (detached).
  2. code-review-graph build -> populates .code-review-graph/ in the repo.
  3. code-review-graph detect-changes --base <parent_sha> -> JSON.
  4. Map JSON to Finding[].
  5. Restore branch.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import time
from pathlib import Path

from bench.runners._venv import ensure_venv, venv_bin
from bench.types import (
    CommitTarget,
    Finding,
    PassAResult,
    PassBResult,
    RunMetrics,
)

_TOOL = "code-review-graph"


def _severity_from_risk(risk: float | None) -> str:
    if risk is None:
        return "info"
    if risk >= 0.75:
        return "critical"
    if risk >= 0.5:
        return "high"
    if risk >= 0.25:
        return "medium"
    if risk > 0:
        return "low"
    return "info"


class CodeReviewGraphRunner:
    name = _TOOL
    upstream_url = "https://github.com/tirth8205/code-review-graph"

    def review_diff(self, target: CommitTarget, budget_usd: float) -> PassAResult:
        ensure_venv(_TOOL, pip_install=["code-review-graph"])
        bin_path = venv_bin(_TOOL, _TOOL)
        repo = target.repo_path
        setup_start = time.monotonic()
        branch = self._git(repo, "symbolic-ref", "--quiet", "--short", "HEAD").strip()
        original_head = branch or self._git(repo, "rev-parse", "HEAD").strip()
        crg_data = repo / ".code-review-graph"
        try:
            self._git(repo, "checkout", "--detach", target.commit_sha)
            subprocess.run(
                [str(bin_path), "build"],
                cwd=str(repo), check=False, capture_output=True, text=True,
            )
            setup_seconds = time.monotonic() - setup_start

            task_start = time.monotonic()
            res = subprocess.run(
                [str(bin_path), "detect-changes", "--base", target.parent_sha],
                cwd=str(repo), check=False, capture_output=True, text=True,
            )
            task_seconds = time.monotonic() - task_start

            findings = self._parse(res.stdout)
            return PassAResult(
                tool=self.name,
                repo=target.repo_name,
                commit_sha=target.commit_sha,
                findings=findings,
                metrics=RunMetrics(
                    setup_seconds=round(setup_seconds, 3),
                    task_seconds=round(task_seconds, 3),
                    tokens_in=0,
                    tokens_out=0,
                    cost_usd=0.0,
                ),
            )
        finally:
            self._git(repo, "checkout", original_head)
            # Don't leave the tool's graph DB inside the user's repo.
            if crg_data.exists():
                shutil.rmtree(crg_data, ignore_errors=True)

    def reproduce_work(self, target: CommitTarget, budget_usd: float) -> PassBResult:
        raise NotImplementedError("code-review-graph has no diff-generation surface")

    @staticmethod
    def _git(repo: Path, *args: str) -> str:
        return subprocess.run(
            ["git", "-C", str(repo), *args],
            check=False, capture_output=True, text=True,
        ).stdout

    @staticmethod
    def _parse(stdout: str) -> list[Finding]:
        if not stdout.strip():
            return []
        try:
            data = json.loads(stdout)
        except json.JSONDecodeError:
            # Some builds prepend log lines; strip everything up to the first `{`.
            i = stdout.find("{")
            if i < 0:
                return []
            try:
                data = json.loads(stdout[i:])
            except json.JSONDecodeError:
                return []

        findings: list[Finding] = []
        risk = data.get("risk_score")
        sev = _severity_from_risk(risk)

        for item in data.get("review_priorities", []):
            findings.append(Finding(
                file=str(item.get("file", "")),
                line_start=item.get("line", item.get("line_start")),
                line_end=item.get("line_end"),
                severity=str(item.get("priority", sev)).lower() or sev,  # type: ignore[arg-type]
                title=str(item.get("title", item.get("reason", "")))[:120],
                body=str(item.get("body", item.get("description", ""))),
                tool=_TOOL,
                raw=item,
            ))
        for gap in data.get("test_gaps", []):
            findings.append(Finding(
                file=str(gap.get("file", "")),
                line_start=gap.get("line"),
                line_end=None,
                severity="low",
                title=f"Untested: {gap.get('symbol', '')}"[:120],
                body=str(gap),
                tool=_TOOL,
                raw=gap,
            ))
        return findings
