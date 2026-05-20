"""Orchestrator. Loads repos.yaml, picks commits, fans out to runners, writes results."""
from __future__ import annotations

import importlib
import subprocess
import time
from collections.abc import Iterable
from datetime import datetime, timezone
from pathlib import Path

import yaml

from bench.ground_truth import collect_signals
from bench.scoring import dump_raw, score_pass_a, write_results_md
from bench.types import CommitTarget, PassAResult, Runner

# v1 runner registry. Stubs raise NotImplementedError so Pass A on real OSS
# fails loud rather than silently dropping a tool.
_BUILTIN_RUNNERS = {
    "polycodegraph": "bench.runners.polycodegraph_runner:PolycodegraphRunner",
    "plain-llm": "bench.runners.plain_llm_runner:PlainLLMRunner",
    "code-review-graph": "bench.runners.code_review_graph_runner:CodeReviewGraphRunner",
    "better-code-review-graph": "bench.runners.better_code_review_graph_runner:BetterCodeReviewGraphRunner",
    "gitnexus": "bench.runners.gitnexus_runner:GitNexusRunner",
    "judini-mcp-code-graph": "bench.runners.judini_runner:JudiniRunner",
    "repomapper": "bench.runners.repomapper_runner:RepoMapperRunner",
    "graphify": "bench.runners.graphify_runner:GraphifyRunner",
}


def _load_runner(spec: str) -> Runner:
    module_path, _, class_name = spec.partition(":")
    mod = importlib.import_module(module_path)
    cls = getattr(mod, class_name)
    return cls()


def _git(repo: Path, *args: str) -> str:
    res = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=False, capture_output=True, text=True,
    )
    return res.stdout


def _resolve_commit(repo_path: Path, ref: str) -> str:
    sha = _git(repo_path, "rev-parse", ref).strip()
    if not sha:
        raise RuntimeError(f"could not resolve ref {ref!r} in {repo_path}")
    return sha


def _build_target(repo_path: Path, repo_name: str, commit_sha: str) -> CommitTarget:
    parent = _git(repo_path, "rev-parse", f"{commit_sha}^").strip() or commit_sha
    diff = _git(repo_path, "diff", parent, commit_sha)
    subj = _git(repo_path, "log", "-1", "--format=%s", commit_sha).strip()
    body = _git(repo_path, "log", "-1", "--format=%b", commit_sha).strip()
    return CommitTarget(
        repo_name=repo_name,
        repo_path=repo_path,
        commit_sha=commit_sha,
        parent_sha=parent,
        pr_title=subj or None,
        pr_body=body or None,
        diff=diff,
    )


def _runs_dir(workspace_root: Path) -> Path:
    return workspace_root / "bench" / "results"


def _new_run_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def run_pass_a(
    *,
    workspace_root: Path,
    repos_config: Path,
    only_tools: Iterable[str] | None = None,
    run_id: str | None = None,
) -> Path:
    """Execute Pass A (review the diff) across every repo and runner.

    Returns the run-directory path.
    """
    cfg = yaml.safe_load(repos_config.read_text())
    selected_tools = list(only_tools) if only_tools else list(_BUILTIN_RUNNERS)

    rid = run_id or _new_run_id()
    run_dir = _runs_dir(workspace_root) / rid
    run_dir.mkdir(parents=True, exist_ok=True)

    all_results: list[PassAResult] = []
    signals_by_commit: dict = {}

    for repo_entry in cfg.get("repos", []):
        name = repo_entry["name"]
        repo_path = (
            (workspace_root / repo_entry["path"]).resolve()
            if "path" in repo_entry
            else _clone(repo_entry["url"], workspace_root / "bench" / "repos_cache" / name)
        )
        for commit_ref in repo_entry.get("commits", ["HEAD"]):
            sha = _resolve_commit(repo_path, commit_ref)
            target = _build_target(repo_path, name, sha)
            signals_by_commit[sha] = collect_signals(repo_path, sha)
            for tool_name in selected_tools:
                runner = _load_runner(_BUILTIN_RUNNERS[tool_name])
                try:
                    result = runner.review_diff(target, budget_usd=5.0)
                except NotImplementedError as exc:
                    result = PassAResult(
                        tool=tool_name, repo=name, commit_sha=sha, findings=[],
                        metrics=_failed_metrics(f"stubbed: {exc}"),
                    )
                except Exception as exc:
                    result = PassAResult(
                        tool=tool_name, repo=name, commit_sha=sha, findings=[],
                        metrics=_failed_metrics(f"crashed: {exc!r}"),
                    )
                all_results.append(result)

    dump_raw(all_results, run_dir / "raw.jsonl")
    scores = score_pass_a(all_results, signals_by_commit)
    write_results_md(scores, run_dir / "RESULTS.md", run_id=rid)
    return run_dir


def _failed_metrics(reason: str):
    from bench.types import RunMetrics
    return RunMetrics(failed=True, failure_reason=reason)


def _clone(url: str, dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if not dest.exists():
        subprocess.run(
            ["git", "clone", "--filter=blob:none", url, str(dest)],
            check=True,
        )
    return dest


# Helper used by smoke tests / debugging.
def measure(seconds_start: float) -> float:
    return round(time.monotonic() - seconds_start, 3)
