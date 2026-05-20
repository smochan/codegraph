"""Shared dataclasses + the runner adapter contract.

Every tool in the comparison set ships a runner module that exposes a
`Runner` subclass implementing `review_diff(...)` and (optionally) `reproduce_work(...)`.
The harness orchestrates runners; runners orchestrate tools.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Protocol

Severity = Literal["info", "low", "medium", "high", "critical"]


@dataclass
class Finding:
    """One issue a tool flagged on a diff."""
    file: str
    line_start: int | None
    line_end: int | None
    severity: Severity
    title: str
    body: str
    tool: str
    raw: dict = field(default_factory=dict)


@dataclass
class RunMetrics:
    """Per-task measurements shared by both passes."""
    setup_seconds: float = 0.0
    task_seconds: float = 0.0
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float = 0.0
    timed_out: bool = False
    failed: bool = False
    failure_reason: str | None = None


@dataclass
class PassAResult:
    tool: str
    repo: str
    commit_sha: str
    findings: list[Finding]
    metrics: RunMetrics


@dataclass
class PassBResult:
    tool: str
    repo: str
    commit_sha: str
    produced_diff: str
    tests_pass: bool | None
    diff_similarity: float | None
    metrics: RunMetrics


@dataclass
class CommitTarget:
    """One unit of work in either pass."""
    repo_name: str
    repo_path: Path
    commit_sha: str
    parent_sha: str
    pr_title: str | None = None
    pr_body: str | None = None
    diff: str = ""


class Runner(Protocol):
    """Contract every tool runner must implement."""
    name: str

    def review_diff(self, target: CommitTarget, budget_usd: float) -> PassAResult:
        ...

    def reproduce_work(self, target: CommitTarget, budget_usd: float) -> PassBResult:
        ...
