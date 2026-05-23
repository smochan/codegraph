"""Pass Q orchestrator: iterate queries x tools, score, write RESULTS.md."""
from __future__ import annotations

import importlib
import json
from collections.abc import Iterable
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean

import yaml

from bench.query_types import QueryResult, QuerySpec

# Only tools that implement query(). Stubs / excluded runners are skipped.
_QUERY_RUNNERS = {
    "polycodegraph": "bench.runners.polycodegraph_runner:PolycodegraphRunner",
    "graphify": "bench.runners.graphify_runner:GraphifyRunner",
    "plain-llm": "bench.runners.plain_llm_runner:PlainLLMRunner",
}


def _load_runner(spec: str):
    module_path, _, class_name = spec.partition(":")
    mod = importlib.import_module(module_path)
    return getattr(mod, class_name)()


def _load_queries(path: Path) -> list[tuple[str, Path, list[QuerySpec]]]:
    cfg = yaml.safe_load(path.read_text())
    out = []
    for repo_name, entry in cfg.get("repos", {}).items():
        repo_path = (Path.cwd() / entry["path"]).resolve()
        specs = [
            QuerySpec(
                id=q["id"],
                kind=q["kind"],
                repo_name=repo_name,
                target=q.get("target"),
                expected_contains=tuple(q.get("expected_contains", [])),
                expected_count_at_least=q.get("expected_count_at_least"),
                notes=q.get("notes", ""),
            )
            for q in entry.get("queries", [])
        ]
        out.append((repo_name, repo_path, specs))
    return out


def run_pass_q(
    *,
    workspace_root: Path,
    queries_config: Path,
    only_tools: Iterable[str] | None = None,
    run_id: str | None = None,
) -> Path:
    """Run every query against every tool and write a Pass-Q results dir."""
    selected_tools = list(only_tools) if only_tools else list(_QUERY_RUNNERS)
    rid = run_id or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_dir = workspace_root / "bench" / "results" / rid
    run_dir.mkdir(parents=True, exist_ok=True)

    all_results: list[QueryResult] = []
    repos_with_queries = _load_queries(queries_config)

    for repo_name, repo_path, specs in repos_with_queries:
        # Per-tool prebuilt flag: first query pays the setup cost, subsequent
        # queries in the same (tool, repo) reuse it.
        built: set[str] = set()
        for spec in specs:
            for tool_name in selected_tools:
                runner_spec = _QUERY_RUNNERS.get(tool_name)
                if not runner_spec:
                    continue
                runner = _load_runner(runner_spec)
                prebuilt = tool_name in built
                try:
                    result = runner.query(spec, repo_path, prebuilt=prebuilt)
                except Exception as exc:
                    result = QueryResult(
                        tool=tool_name, query_id=spec.id, repo_name=repo_name,
                        failed=True, failure_reason=f"crashed: {exc!r}",
                    )
                all_results.append(result)
                if not result.failed:
                    built.add(tool_name)

    _dump_raw(all_results, run_dir / "raw_queries.jsonl")
    _write_results(all_results, repos_with_queries, run_dir / "RESULTS.md", run_id=rid)
    return run_dir


def _dump_raw(results: list[QueryResult], out: Path) -> None:
    with out.open("w") as f:
        for r in results:
            f.write(json.dumps(asdict(r)) + "\n")


def _write_results(
    results: list[QueryResult],
    repos: list[tuple[str, Path, list[QuerySpec]]],
    out: Path,
    *, run_id: str,
) -> None:
    lines: list[str] = [
        f"# Benchmark results — Pass Q — run `{run_id}`",
        "",
        "Each query is run against every tool with `query()` support. "
        "Plain-LLM has no graph; it gets the question + a grep-filtered file dump as context.",
        "",
    ]

    by_repo: dict[str, list[QueryResult]] = {}
    for r in results:
        by_repo.setdefault(r.repo_name, []).append(r)

    for repo_name, _path, specs in repos:
        rows = by_repo.get(repo_name, [])
        if not rows:
            continue
        lines += [
            f"## Repo: `{repo_name}`",
            "",
            "### Per-query correctness",
            "",
            "| Query | Kind | " + " | ".join(_tool_columns(rows)) + " |",
            "|---|---|" + "|".join(["---"] * len(_tool_columns(rows))) + "|",
        ]
        for spec in specs:
            cells = []
            for tool in _tool_columns(rows):
                r = _find(rows, spec.id, tool)
                cells.append(_cell(r))
            lines.append(f"| `{spec.id}` | {spec.kind} | " + " | ".join(cells) + " |")

        # Aggregate row: latency + tokens averaged per tool.
        lines += [
            "",
            "### Aggregate per tool",
            "",
            "| Tool | Queries | Correct | Setup (s) | Avg latency (s) | Avg tokens returned | Cost (USD) | Failures |",
            "|------|--------:|--------:|----------:|----------------:|--------------------:|-----------:|---------:|",
        ]
        for tool in _tool_columns(rows):
            tool_rows = [r for r in rows if r.tool == tool]
            ok = [r for r in tool_rows if not r.failed]
            correct = sum(1 for r in ok if r.correct)
            setup = round(sum(r.setup_seconds for r in ok), 2)
            avg_lat = round(mean([r.latency_seconds for r in ok]) if ok else 0.0, 4)
            avg_tok = round(mean([r.tokens_returned for r in ok]) if ok else 0.0, 0)
            cost = round(sum(r.cost_usd for r in ok), 4)
            lines.append(
                f"| `{tool}` | {len(tool_rows)} | {correct} | {setup} | {avg_lat} | "
                f"{int(avg_tok)} | {cost} | {sum(1 for r in tool_rows if r.failed)} |"
            )
        lines.append("")

    lines += [
        "## Methodology",
        "",
        "- A query is **correct** if every expected substring appears anywhere in the tool's response. ",
        "  For listing queries (untested, cycles) it's correct if the tool returns at least N items.",
        "- Setup time is the one-time graph build per (tool, repo). Subsequent queries reuse it.",
        "- Tokens returned is a coarse word-count proxy. It tracks *ratio* across tools, not absolute LLM tokens.",
        "- Plain-LLM runs against a grep-filtered file dump, the honest baseline for \"what if you had no graph\".",
        "",
    ]
    out.write_text("\n".join(lines))


def _tool_columns(rows: list[QueryResult]) -> list[str]:
    return sorted({r.tool for r in rows})


def _find(rows: list[QueryResult], query_id: str, tool: str) -> QueryResult | None:
    for r in rows:
        if r.query_id == query_id and r.tool == tool:
            return r
    return None


def _cell(r: QueryResult | None) -> str:
    if r is None:
        return "—"
    if r.failed:
        return f"❌ ({(r.failure_reason or '')[:40]})"
    mark = "✅" if r.correct else "❌"
    return f"{mark} {r.latency_seconds}s · {r.tokens_returned} tok"
