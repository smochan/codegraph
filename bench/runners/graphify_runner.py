"""Graphify adapter — Pass A graph-only baseline; Pass Q via `graphify query`."""
from __future__ import annotations

import subprocess
import time
from pathlib import Path

from bench.query_types import QueryResult, QuerySpec, approx_tokens, matches
from bench.runners._graph_only import GraphOnlyRunner
from bench.runners._venv import ensure_venv, venv_bin
from bench.types import CommitTarget

_QUESTION_FOR_KIND = {
    "find_symbol": "Where is the function `{target}` defined?",
    "callers": "Which functions call `{target}`?",
    "subgraph": "What does `{target}` depend on?",
    "untested": "Which functions have no tests?",
    "cycles": "What import or call cycles exist in this codebase?",
}


class GraphifyRunner(GraphOnlyRunner):
    name = "graphify"
    upstream_url = "https://github.com/safishamsi/graphify"
    clean_dirs = ("graphify-out",)

    def build_argv(self, target: CommitTarget) -> list[str]:
        ensure_venv(self.name, pip_install=["graphifyy"])
        bin_path = venv_bin(self.name, "graphify")
        return [str(bin_path), "update", str(target.repo_path), "--no-cluster"]

    # --- Pass Q ----------------------------------------------------------

    def query(self, spec: QuerySpec, repo: Path, *, prebuilt: bool = False) -> QueryResult:
        ensure_venv(self.name, pip_install=["graphifyy"])
        bin_path = venv_bin(self.name, "graphify")

        setup_start = time.monotonic()
        graph_path = repo / "graphify-out" / "graph.json"
        if not prebuilt or not graph_path.exists():
            subprocess.run(
                [str(bin_path), "update", str(repo), "--no-cluster"],
                cwd=str(repo), check=False, capture_output=True, text=True,
            )
        setup_seconds = time.monotonic() - setup_start

        question = _QUESTION_FOR_KIND.get(spec.kind)
        if question is None:
            return self._fail(spec, repo.name, f"unknown kind {spec.kind}", setup_seconds)
        if spec.target:
            question = question.format(target=spec.target)

        task_start = time.monotonic()
        res = subprocess.run(
            [str(bin_path), "query", question, "--graph", str(graph_path)],
            cwd=str(repo), check=False, capture_output=True, text=True,
        )
        latency = time.monotonic() - task_start
        text = res.stdout

        # Graphify returns a free-form BFS result. We split lines and treat each
        # non-empty line as an item.
        items = [ln.strip() for ln in text.splitlines() if ln.strip()]
        return QueryResult(
            tool=self.name,
            query_id=spec.id,
            repo_name=spec.repo_name,
            items=items,
            raw_text=text,
            correct=matches(spec, items, text),
            latency_seconds=round(latency, 4),
            setup_seconds=round(setup_seconds if not prebuilt else 0.0, 3),
            tokens_returned=approx_tokens(text),
            cost_usd=0.0,
        )

    @staticmethod
    def _fail(spec: QuerySpec, repo_name: str, reason: str, setup_s: float) -> QueryResult:
        return QueryResult(
            tool="graphify",
            query_id=spec.id,
            repo_name=repo_name,
            failed=True,
            failure_reason=reason,
            setup_seconds=round(setup_s, 3),
        )
