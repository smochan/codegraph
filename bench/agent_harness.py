"""Claude-Code-style agent harness.

For each (configuration, question) pair:
  1. Spawn the configuration's MCP servers (stdio).
  2. Convert their tools to Anthropic tool definitions.
  3. Loop: call Claude -> if tool_use, route to the right MCP -> feed result back.
  4. Stop when Claude produces a stop_reason='end_turn' message.
  5. Record: final answer, total tokens, # tool calls, latency, cost, correctness.

Same host LLM across every configuration. Only the registered MCP tools change.
"""
from __future__ import annotations

import asyncio
import json
import os
from collections.abc import Iterable
from contextlib import AsyncExitStack
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean

import yaml
from anthropic import Anthropic

from bench.mcp_client import (
    McpServerSpec,
    McpSession,
    find_session,
    to_anthropic_tools,
)
from bench.query_harness import _load_queries
from bench.query_types import QuerySpec, matches

DEFAULT_MODEL = "claude-sonnet-4-6"
MAX_AGENT_TURNS = 12  # ceiling on tool-call iterations
PRICE_PER_MTOK_USD = {
    "claude-sonnet-4-6": {"in": 3.0, "out": 15.0},
}

QUESTION_FOR_KIND = {
    "find_symbol": (
        "Where is `{target}` defined in this codebase? Return the qualified name "
        "and the file path. If you cannot determine, say so explicitly."
    ),
    "callers": (
        "Which functions or methods in this codebase call `{target}`? "
        "Return qualified names (or 'no in-repo callers' if there are none)."
    ),
    "subgraph": (
        "What does `{target}` directly call or depend on? "
        "Return qualified names of its immediate neighbors."
    ),
    "untested": (
        "List at least 10 functions in this codebase that have no tests covering them. "
        "Return qualified names."
    ),
    "cycles": (
        "Are there any import cycles or call cycles in this codebase? "
        "If yes, describe one with the involved qualified names."
    ),
}


@dataclass
class AgentResult:
    config: str
    query_id: str
    repo_name: str
    final_answer: str = ""
    tool_calls: list[dict] = field(default_factory=list)
    correct: bool = False
    turns: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float = 0.0
    latency_seconds: float = 0.0
    failed: bool = False
    failure_reason: str | None = None


def _question_for(spec: QuerySpec) -> str:
    template = QUESTION_FOR_KIND.get(spec.kind, "What is `{target}`?")
    return template.format(target=spec.target) if spec.target else template


def _expand_server_specs(cfg_entry: dict, repo_path: Path, workspace_root: Path) -> list[McpServerSpec]:
    out: list[McpServerSpec] = []
    for s in cfg_entry.get("servers", []):
        cwd = repo_path if s.get("cwd_is_target_repo") else workspace_root
        # Make `command` absolute (resolve relative to workspace_root, not cwd).
        cmd_path = Path(s["command"])
        if not cmd_path.is_absolute():
            cmd_path = (workspace_root / cmd_path).resolve()
        out.append(McpServerSpec(
            name=s["name"],
            command=str(cmd_path),
            args=s.get("args", []),
            cwd=cwd,
            env=None,
        ))
    return out


async def _run_one(
    *,
    client: Anthropic,
    model: str,
    config_name: str,
    server_specs: list[McpServerSpec],
    spec: QuerySpec,
    repo_path: Path,
) -> AgentResult:
    """Run one (configuration, query) tuple to completion."""
    result = AgentResult(
        config=config_name,
        query_id=spec.id,
        repo_name=spec.repo_name,
    )
    question = _question_for(spec)
    started = asyncio.get_event_loop().time()

    async with AsyncExitStack() as stack:
        sessions: list[McpSession] = []
        for s in server_specs:
            sess = await stack.enter_async_context(McpSession(s))
            sessions.append(sess)
        tools = to_anthropic_tools(sessions)

        messages = [{"role": "user", "content": question}]
        for turn in range(MAX_AGENT_TURNS):
            result.turns = turn + 1
            create_kwargs = dict(
                model=model,
                max_tokens=2048,
                messages=messages,
                system=(
                    "You are answering a question about a specific Python codebase. "
                    "If MCP tools are available, use them to look up real answers from the repo. "
                    "If no tools are available, answer as best you can from general knowledge. "
                    "Be concise. Return qualified names + file paths whenever possible."
                ),
            )
            if tools:
                create_kwargs["tools"] = tools

            response = await asyncio.to_thread(client.messages.create, **create_kwargs)
            result.tokens_in += response.usage.input_tokens
            result.tokens_out += response.usage.output_tokens

            # Stash the assistant's reply.
            messages.append({"role": "assistant", "content": response.content})

            if response.stop_reason != "tool_use":
                # Done. Collapse text blocks into final_answer.
                final = []
                for block in response.content:
                    if getattr(block, "type", "") == "text":
                        final.append(block.text)
                result.final_answer = "\n".join(final)
                break

            # Tool-use turn: route each tool_use block to the right MCP.
            tool_results = []
            for block in response.content:
                if getattr(block, "type", "") != "tool_use":
                    continue
                qualified = block.name
                args = block.input or {}
                routed = find_session(sessions, qualified)
                if routed is None:
                    payload = f"error: no MCP server exposes tool {qualified!r}"
                    is_error = True
                else:
                    session, real_name = routed
                    try:
                        payload = await session.call(real_name, args)
                        is_error = False
                    except Exception as exc:  # noqa: BLE001
                        payload = f"tool call failed: {exc!r}"
                        is_error = True
                result.tool_calls.append({
                    "name": qualified,
                    "input": args,
                    "output_preview": payload[:200],
                    "is_error": is_error,
                })
                # Anthropic rejects empty `content` strings — substitute a placeholder
                # so the agent loop survives MCP servers that return no content blocks.
                content = payload[:50_000] or "(tool returned no content)"
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": content,
                    "is_error": is_error,
                })
            messages.append({"role": "user", "content": tool_results})
        else:
            result.failed = True
            result.failure_reason = f"hit MAX_AGENT_TURNS ({MAX_AGENT_TURNS})"

    result.latency_seconds = round(asyncio.get_event_loop().time() - started, 3)
    prices = PRICE_PER_MTOK_USD.get(model, {"in": 0.0, "out": 0.0})
    result.cost_usd = round(
        result.tokens_in / 1_000_000 * prices["in"]
        + result.tokens_out / 1_000_000 * prices["out"],
        5,
    )

    # Correctness: check final_answer (and tool call previews) against expected.
    haystack = result.final_answer + "\n" + "\n".join(
        tc.get("output_preview", "") for tc in result.tool_calls
    )
    items = [tc["name"] for tc in result.tool_calls]
    result.correct = matches(spec, items, haystack)
    return result


def run_agent_bench(
    *,
    workspace_root: Path,
    configurations_path: Path,
    queries_path: Path,
    only_configs: Iterable[str] | None = None,
    only_queries: Iterable[str] | None = None,
    model: str = DEFAULT_MODEL,
    run_id: str | None = None,
) -> Path:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError(
            "ANTHROPIC_API_KEY missing. Add it to ~/.config/secrets/keys.env, "
            "then run `seedenv .` from the codegraph repo."
        )
    client = Anthropic(api_key=api_key)

    cfg = yaml.safe_load(configurations_path.read_text())["configurations"]
    selected_configs = list(only_configs) if only_configs else list(cfg)
    selected_query_ids = set(only_queries) if only_queries else None

    rid = run_id or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_dir = workspace_root / "bench" / "results" / rid
    run_dir.mkdir(parents=True, exist_ok=True)

    all_results: list[AgentResult] = []
    repos_with_queries = _load_queries(queries_path)

    for config_name in selected_configs:
        if config_name not in cfg:
            raise RuntimeError(f"unknown config {config_name!r}")
        cfg_entry = cfg[config_name]
        for repo_name, repo_path, specs in repos_with_queries:
            server_specs = _expand_server_specs(cfg_entry, repo_path, workspace_root)
            for spec in specs:
                if selected_query_ids and spec.id not in selected_query_ids:
                    continue
                try:
                    result = asyncio.run(_run_one(
                        client=client,
                        model=model,
                        config_name=config_name,
                        server_specs=server_specs,
                        spec=spec,
                        repo_path=repo_path,
                    ))
                except Exception as exc:  # noqa: BLE001
                    result = AgentResult(
                        config=config_name, query_id=spec.id, repo_name=repo_name,
                        failed=True, failure_reason=f"crashed: {exc!r}",
                    )
                all_results.append(result)
                print(
                    f"[{config_name}] {repo_name}/{spec.id} "
                    f"{'OK ' if result.correct else 'NO '}"
                    f"turns={result.turns} tokens={result.tokens_in}+{result.tokens_out} "
                    f"cost=${result.cost_usd}"
                )

    _dump_raw(all_results, run_dir / "agent_raw.jsonl")
    _write_results_md(all_results, repos_with_queries, run_dir / "RESULTS_AGENT.md", rid=rid, model=model)
    return run_dir


def _dump_raw(results: list[AgentResult], out: Path) -> None:
    with out.open("w") as f:
        for r in results:
            f.write(json.dumps(asdict(r)) + "\n")


def _write_results_md(
    results: list[AgentResult],
    repos: list[tuple[str, Path, list[QuerySpec]]],
    out: Path,
    *, rid: str, model: str,
) -> None:
    lines: list[str] = [
        f"# Claude-Code-style agent benchmark — run `{rid}`",
        "",
        f"Host LLM: `{model}` (same across every configuration).",
        "Only the MCP tools exposed to Claude change between configurations.",
        "",
    ]
    by_repo: dict[str, list[AgentResult]] = {}
    for r in results:
        by_repo.setdefault(r.repo_name, []).append(r)

    for repo_name, _path, _specs in repos:
        rows = by_repo.get(repo_name, [])
        if not rows:
            continue
        configs = sorted({r.config for r in rows})
        lines += [
            f"## Repo: `{repo_name}`",
            "",
            "| Configuration | Correct | Avg turns | Avg tool-calls | Tokens in | Tokens out | Cost (USD) | Avg latency (s) |",
            "|---|---:|----:|----:|----:|----:|----:|----:|",
        ]
        for c in configs:
            rs = [r for r in rows if r.config == c]
            ok = [r for r in rs if not r.failed]
            correct = sum(1 for r in ok if r.correct)
            lines.append(
                f"| `{c}` | {correct}/{len(rs)} | "
                f"{round(mean([r.turns for r in ok]) if ok else 0, 1)} | "
                f"{round(mean([len(r.tool_calls) for r in ok]) if ok else 0, 1)} | "
                f"{sum(r.tokens_in for r in ok)} | "
                f"{sum(r.tokens_out for r in ok)} | "
                f"{round(sum(r.cost_usd for r in ok), 4)} | "
                f"{round(mean([r.latency_seconds for r in ok]) if ok else 0, 2)} |"
            )
        lines.append("")

    lines += [
        "## How to read this",
        "",
        "- Same host LLM across every row. Only the registered MCP tools change.",
        "- `Tokens in` is the sum of context fed to Claude across the whole agent loop, including",
        "  tool-result payloads. This is the number users actually pay for in real coding-assistant use.",
        "- `Tokens out` is Claude's generated output across the loop.",
        "- A query is correct if either the model's final answer or any tool-call output contains the expected hits.",
        "",
    ]
    out.write_text("\n".join(lines))
