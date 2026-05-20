"""polycodegraph runner — shells out to the same CLI a user runs.

Pass A flow:
  1. git checkout parent_sha (saved on a detached HEAD).
  2. codegraph build  -> baseline graph in tmp data dir.
  3. codegraph baseline save bench-parent.
  4. git checkout commit_sha.
  5. codegraph build  -> head graph.
  6. codegraph review --format json --baseline <bench-parent> -> findings.
  7. Restore original HEAD.

We use a per-run temp data dir (`--data-dir`) so we never collide with the
user's real .codegraph directory.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from bench.query_types import QueryResult, QuerySpec, approx_tokens, matches
from bench.types import (
    CommitTarget,
    Finding,
    PassAResult,
    PassBResult,
    RunMetrics,
)

_SEVERITY_MAP = {
    "critical": "critical",
    "high": "high",
    "med": "medium",
    "medium": "medium",
    "low": "low",
    "info": "info",
}


class PolycodegraphRunner:
    name = "polycodegraph"

    def review_diff(self, target: CommitTarget, budget_usd: float) -> PassAResult:
        repo = target.repo_path
        setup_start = time.monotonic()
        # Prefer the branch name so we don't leave the user on a detached HEAD
        # after the run completes. Falls back to SHA if already detached.
        branch = self._git(repo, "symbolic-ref", "--quiet", "--short", "HEAD").strip()
        original_head = branch or self._git(repo, "rev-parse", "HEAD").strip()
        data_dir = Path(tempfile.mkdtemp(prefix="cgbench-"))
        try:
            # Baseline at parent.
            self._git(repo, "checkout", "--detach", target.parent_sha)
            self._cg(repo, data_dir, "build")
            baseline_path = data_dir / "baseline.db"
            self._cg(repo, data_dir, "baseline", "save", "--output", str(baseline_path))

            # Head at commit_sha.
            self._git(repo, "checkout", "--detach", target.commit_sha)
            self._cg(repo, data_dir, "build")
            setup_seconds = time.monotonic() - setup_start

            # Run review with JSON output.
            task_start = time.monotonic()
            out_path = data_dir / "review.json"
            self._cg(
                repo, data_dir, "review",
                "--baseline", str(baseline_path),
                "--format", "json",
                "--output", str(out_path),
                # Don't let CLI exit-1 on findings derail us.
                "--block-on", "critical",
            )
            task_seconds = time.monotonic() - task_start

            findings = self._parse_findings(out_path)
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

    def reproduce_work(self, target: CommitTarget, budget_usd: float) -> PassBResult:
        raise NotImplementedError("Pass B for polycodegraph deferred to v2")

    # ------------------------------------------------------------------
    # Pass Q (query benchmark)
    # ------------------------------------------------------------------

    def query(self, spec: QuerySpec, repo: Path, *, prebuilt: bool = False) -> QueryResult:
        """Run one query against this repo's polycodegraph graph."""
        setup_start = time.monotonic()
        if not prebuilt:
            self._cg(repo, repo / ".codegraph", "build")
        setup_seconds = time.monotonic() - setup_start

        # In-process query — same code path the MCP server uses.
        from codegraph.graph.store_networkx import to_digraph
        from codegraph.graph.store_sqlite import SQLiteGraphStore

        db_path = repo / ".codegraph" / "graph.db"
        if not db_path.exists():
            return self._fail(spec, repo.name, "no graph after build", setup_seconds)

        task_start = time.monotonic()
        store = SQLiteGraphStore(db_path)
        try:
            graph = to_digraph(store)
            items, raw = self._dispatch(spec, graph)
        except Exception as exc:
            return self._fail(spec, repo.name, f"crashed: {exc!r}", setup_seconds)
        finally:
            store.close()
        latency = time.monotonic() - task_start

        return QueryResult(
            tool=self.name,
            query_id=spec.id,
            repo_name=spec.repo_name,
            items=items,
            raw_text=raw,
            correct=matches(spec, items, raw),
            latency_seconds=round(latency, 4),
            setup_seconds=round(setup_seconds if not prebuilt else 0.0, 3),
            tokens_returned=approx_tokens(raw),
            cost_usd=0.0,
        )

    @staticmethod
    def _dispatch(spec: QuerySpec, graph):  # type: ignore[no-untyped-def]
        from codegraph.analysis.blast_radius import blast_radius
        from codegraph.analysis.cycles import find_cycles
        from codegraph.analysis.report import find_symbol
        from codegraph.analysis.untested import find_untested
        from codegraph.graph.store_networkx import subgraph_around

        if spec.kind == "find_symbol":
            assert spec.target
            qn = find_symbol(graph, spec.target)
            if qn is None:
                return [], f"symbol {spec.target!r} not found"
            file_ = graph.nodes[qn].get("file", "")
            line = graph.nodes[qn].get("line", "")
            return [qn, file_], f"{qn}  ({file_}:{line})"

        if spec.kind == "callers":
            assert spec.target
            qn = find_symbol(graph, spec.target)
            if qn is None:
                return [], f"symbol {spec.target!r} not found"
            res = blast_radius(graph, qn, depth=1)
            items = [
                graph.nodes[n].get("qualname", str(n)) for n in res.nodes
            ]
            return items, "\n".join(items)

        if spec.kind == "subgraph":
            assert spec.target
            qn = find_symbol(graph, spec.target)
            if qn is None:
                return [], f"symbol {spec.target!r} not found"
            sub = subgraph_around(graph, qn, depth=1)
            items = [
                graph.nodes[n].get("qualname", str(n)) for n in sub.nodes
            ]
            return items, "\n".join(items)

        if spec.kind == "untested":
            rows = find_untested(graph)
            items = [r.qualname for r in rows[:50]]
            return items, "\n".join(items)

        if spec.kind == "cycles":
            report = find_cycles(graph)
            items = [
                " -> ".join(c.qualnames)
                for c in (*report.import_cycles, *report.call_cycles)
            ]
            return items, "\n".join(items)

        return [], f"unknown query kind: {spec.kind}"

    @classmethod
    def _fail(cls, spec: QuerySpec, repo_name: str, reason: str, setup_s: float) -> QueryResult:
        return QueryResult(
            tool=cls.name,
            query_id=spec.id,
            repo_name=repo_name,
            failed=True,
            failure_reason=reason,
            setup_seconds=round(setup_s, 3),
        )

    @staticmethod
    def _git(repo: Path, *args: str) -> str:
        res = subprocess.run(
            ["git", "-C", str(repo), *args],
            check=False, capture_output=True, text=True,
        )
        return res.stdout

    @staticmethod
    def _cg_bin() -> list[str]:
        # Prefer a `codegraph` binary that lives next to the current Python.
        # Falls back to PATH, then to `python -m codegraph` via runpy.
        cand = Path(sys.executable).with_name("codegraph")
        if cand.exists():
            return [str(cand)]
        on_path = shutil.which("codegraph")
        if on_path:
            return [on_path]
        return [sys.executable, "-m", "codegraph.cli"]

    @classmethod
    def _cg(cls, repo: Path, data_dir: Path, *args: str) -> str:
        res = subprocess.run(
            [*cls._cg_bin(), "--data-dir", str(data_dir), *args],
            check=False, capture_output=True, text=True, cwd=str(repo),
        )
        # Don't raise; the harness wraps the runner and records failures.
        return res.stdout

    @staticmethod
    def _parse_findings(out_path: Path) -> list[Finding]:
        if not out_path.exists():
            return []
        try:
            data = json.loads(out_path.read_text())
        except json.JSONDecodeError:
            return []
        findings: list[Finding] = []
        for item in data.get("findings", []):
            sev_raw = str(item.get("severity", "info")).lower()
            findings.append(Finding(
                file=str(item.get("file", "") or ""),
                line_start=item.get("line_start"),
                line_end=item.get("line_end"),
                severity=_SEVERITY_MAP.get(sev_raw, "info"),
                title=str(item.get("title", item.get("rule", ""))),
                body=str(item.get("message", item.get("body", ""))),
                tool="polycodegraph",
                raw=item,
            ))
        return findings
