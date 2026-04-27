"""Chunk a codegraph SQLite store into embeddable units."""
from __future__ import annotations

from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from codegraph.graph.schema import Node, NodeKind
from codegraph.graph.store_sqlite import SQLiteGraphStore

# Node kinds that produce a chunk by default.  MODULE / FILE / TEST / IMPORT /
# VARIABLE / PARAMETER are skipped: they're either coarse, generated, or
# duplicate the chunks of the symbols they contain.
_DEFAULT_KINDS: frozenset[NodeKind] = frozenset(
    {NodeKind.FUNCTION, NodeKind.METHOD, NodeKind.CLASS}
)


@dataclass(frozen=True)
class Chunk:
    """A single embeddable code chunk pulled from the graph + source."""

    qualname: str
    file: str
    line_start: int
    line_end: int
    kind: str
    text: str
    params: list[str] = field(default_factory=list)
    returns: str | None = None
    role: str | None = None

    @property
    def id(self) -> str:
        """Stable id for upsert / dedupe."""
        return f"{self.file}::{self.qualname}::{self.line_start}"


def _read_lines(repo_root: Path, file: str) -> list[str]:
    """Best-effort read; returns ``[]`` on any IO error."""
    try:
        return (repo_root / file).read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        return []


def _slice(lines: list[str], start: int, end: int) -> str:
    if not lines:
        return ""
    s = max(0, start - 1)
    e = max(s, min(len(lines), end))
    return "\n".join(lines[s:e])


def _md_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(v) for v in value]
    return []


def _node_to_chunk(node: Node, repo_root: Path, _cache: dict[str, list[str]]) -> Chunk | None:
    lines = _cache.get(node.file)
    if lines is None:
        lines = _read_lines(repo_root, node.file)
        _cache[node.file] = lines

    body = _slice(lines, node.line_start, node.line_end)
    if not body.strip():
        # Fall back to signature / docstring so we still index something useful.
        body = "\n".join(filter(None, [node.signature or "", node.docstring or ""]))
    if not body.strip():
        return None

    md = node.metadata or {}
    role_val = md.get("role") if isinstance(md, dict) else None
    returns_val = md.get("returns") if isinstance(md, dict) else None

    return Chunk(
        qualname=node.qualname,
        file=node.file,
        line_start=node.line_start,
        line_end=node.line_end,
        kind=node.kind.value,
        text=body,
        params=_md_list(md.get("params")) if isinstance(md, dict) else [],
        returns=str(returns_val) if returns_val is not None else None,
        role=str(role_val) if role_val is not None else None,
    )


def chunk_repo(
    repo_root: Path,
    *,
    db_path: Path | None = None,
    kinds: Iterable[NodeKind] | None = None,
) -> Iterator[Chunk]:
    """Yield one :class:`Chunk` per matching graph node.

    ``kinds`` defaults to FUNCTION / METHOD / CLASS.
    """
    db = db_path or (repo_root / ".codegraph" / "graph.db")
    if not db.exists():
        raise FileNotFoundError(
            f"No graph database at {db}. Run `codegraph build` first."
        )

    selected = frozenset(kinds) if kinds is not None else _DEFAULT_KINDS
    line_cache: dict[str, list[str]] = {}

    store = SQLiteGraphStore(db)
    try:
        for node in store.iter_nodes():
            if node.kind not in selected:
                continue
            chunk = _node_to_chunk(node, repo_root, line_cache)
            if chunk is not None:
                yield chunk
    finally:
        store.close()
