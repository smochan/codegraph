"""Heuristic ground-truth labeler for Pass A.

A finding on commit C is considered a *true positive* if it overlaps with any
known bug signal we can reconstruct from git history:

1. A follow-up commit within 30 days touches the same file/line range and its
   message contains `fix`, `bug`, or `revert`.
2. The commit was reverted (a later commit with subject `Revert "<C subject>"`).
3. (Optional, only when GH token available) A GitHub issue references the
   commit SHA within 60 days of merge.

This is a heuristic. We disclose it in RESULTS.md, hand-label a 20-PR
calibration subset, and report heuristic-vs-human agreement.
"""
from __future__ import annotations

import subprocess
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

_FIX_TOKENS = ("fix", "bug", "revert", "hotfix", "patch")


@dataclass
class BugSignal:
    """One reason we think a commit introduced a bug."""
    kind: str  # "follow_up_commit" | "revert" | "issue"
    evidence: str
    file_hint: str | None = None
    line_hint: int | None = None


def _git(repo: Path, *args: str) -> str:
    res = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=False,
        capture_output=True,
        text=True,
    )
    return res.stdout


def collect_signals(repo: Path, commit_sha: str, window_days: int = 30) -> list[BugSignal]:
    """Return everything that suggests commit_sha shipped a bug."""
    signals: list[BugSignal] = []

    # 1. Revert detection.
    subject = _git(repo, "log", "-1", "--format=%s", commit_sha).strip()
    if subject:
        revert_subject = f'Revert "{subject}"'
        revert_log = _git(
            repo, "log", "--all", f'--grep={revert_subject}', "--format=%H %s",
        ).strip()
        for line in revert_log.splitlines():
            if line.strip():
                signals.append(BugSignal(kind="revert", evidence=line.strip()))

    # 2. Follow-up commits within window_days touching same files.
    commit_date = _git(repo, "log", "-1", "--format=%cI", commit_sha).strip()
    if commit_date:
        try:
            dt = datetime.fromisoformat(commit_date.replace("Z", "+00:00"))
        except ValueError:
            dt = None
        if dt is not None:
            window_end = (dt + timedelta(days=window_days)).isoformat()
            touched_files = _git(
                repo, "diff-tree", "--no-commit-id", "--name-only", "-r", commit_sha,
            ).splitlines()
            touched = {f.strip() for f in touched_files if f.strip()}
            if touched:
                log = _git(
                    repo, "log",
                    f"--since={commit_date}",
                    f"--until={window_end}",
                    "--format=%H%x09%s",
                    "--",
                    *touched,
                )
                for line in log.splitlines():
                    if "\t" not in line:
                        continue
                    sha, subj = line.split("\t", 1)
                    if sha == commit_sha:
                        continue
                    if any(tok in subj.lower() for tok in _FIX_TOKENS):
                        signals.append(
                            BugSignal(
                                kind="follow_up_commit",
                                evidence=f"{sha[:10]} {subj}",
                            )
                        )

    return signals


def is_true_positive(
    *, signals: list[BugSignal], finding_file: str, finding_line: int | None,
) -> bool:
    """A finding is a TP if it overlaps with any bug signal.

    v1 overlap is coarse: same file. Line-range overlap is a v2 refinement.
    """
    if not signals:
        return False
    return any(s.file_hint is None or s.file_hint == finding_file for s in signals)
