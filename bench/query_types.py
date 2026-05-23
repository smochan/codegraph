"""Shared dataclasses for Pass Q (query benchmark)."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

QueryKind = Literal[
    "find_symbol",
    "callers",
    "subgraph",
    "untested",
    "cycles",
]


@dataclass(frozen=True)
class QuerySpec:
    """One query to run against every tool."""
    id: str
    kind: QueryKind
    repo_name: str
    target: str | None = None
    expected_contains: tuple[str, ...] = ()
    expected_count_at_least: int | None = None
    notes: str = ""


@dataclass
class QueryResult:
    tool: str
    query_id: str
    repo_name: str
    items: list[str] = field(default_factory=list)
    raw_text: str = ""
    correct: bool = False
    latency_seconds: float = 0.0
    setup_seconds: float = 0.0  # one-time graph build (charged on first query per (tool, repo))
    tokens_returned: int = 0    # rough word-count proxy
    cost_usd: float = 0.0
    failed: bool = False
    failure_reason: str | None = None


def approx_tokens(text: str) -> int:
    """Cheap token-count proxy: word count. Tracks ratio between tools, not absolute."""
    return len(text.split())


def matches(spec: QuerySpec, items: list[str], raw_text: str) -> bool:
    """Subset match: every expected substring must appear in items or raw_text.

    Liberal on purpose — we're measuring "did the tool find the right thing",
    not "did it return exactly this and nothing else".
    """
    haystack = "\n".join([*items, raw_text]).lower()
    if spec.expected_contains:
        return all(needle.lower() in haystack for needle in spec.expected_contains)
    if spec.expected_count_at_least is not None:
        return len(items) >= spec.expected_count_at_least
    return True
