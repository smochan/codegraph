"""Repo walker and incremental graph builder."""
from __future__ import annotations

import hashlib
import logging
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pathspec

# Ensure extractors register themselves.
import codegraph.parsers.python
import codegraph.parsers.typescript  # noqa: F401
from codegraph.config import CodegraphConfig
from codegraph.graph.schema import Node, NodeKind, make_node_id
from codegraph.graph.store_sqlite import SQLiteGraphStore
from codegraph.parsers.base import get_extractor_for
from codegraph.parsers.python import PythonExtractor

logger = logging.getLogger(__name__)

_BUILTIN_IGNORES = [
    ".git", ".venv", "venv", "node_modules", ".codegraph",
    "dist", "build", "__pycache__", ".next", ".pytest_cache",
    ".mypy_cache", ".ruff_cache", ".tox", ".eggs", "*.egg-info",
    ".DS_Store", "*.pyc", "*.pyo",
]

_IGNORE_DIRS: set[str] = {
    ".git", ".venv", "venv", "node_modules", ".codegraph",
    "dist", "build", "__pycache__", ".next", ".pytest_cache",
    ".mypy_cache", ".ruff_cache", ".tox",
}


@dataclass
class BuildStats:
    files_scanned: int = 0
    files_parsed: int = 0
    nodes_added: int = 0
    edges_added: int = 0
    files_skipped: int = 0
    errors: list[str] = field(default_factory=list)


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _get_git_sha(repo_root: Path) -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass
    return None


class GraphBuilder:
    def __init__(
        self,
        repo_root: Path,
        store: SQLiteGraphStore,
        ignore: list[str] | None = None,
        config: CodegraphConfig | None = None,
    ) -> None:
        self._repo_root = repo_root
        self._store = store
        self._ignore = ignore or []
        self._config = config or CodegraphConfig()
        self._apply_config_to_extractors()

    def _apply_config_to_extractors(self) -> None:
        """Forward user dead-code patterns onto the singleton extractors."""
        extra = tuple(self._config.dead_code.entry_point_decorators)
        # PythonExtractor is registered as a singleton in the registry; we
        # mutate its class attribute so subsequent parse_file calls pick up
        # the user patterns.
        PythonExtractor.extra_entry_point_decorators = extra

    def build(self, incremental: bool = True) -> BuildStats:
        stats = BuildStats()
        patterns = _BUILTIN_IGNORES + self._ignore
        spec = pathspec.PathSpec.from_lines("gitwildmatch", patterns)

        files = list(self._walk_repo(spec))
        stats.files_scanned = len(files)

        for file_path in files:
            rel = file_path.relative_to(self._repo_root).as_posix()
            try:
                content_hash = _sha256(file_path)

                extractor = get_extractor_for(file_path)
                language = extractor.language if extractor else "unknown"

                file_node_id = make_node_id(NodeKind.FILE, rel, rel)
                if incremental:
                    existing = self._store.get_node(file_node_id)
                    if existing and existing.content_hash == content_hash:
                        stats.files_skipped += 1
                        continue

                self._store.delete_file(rel)

                file_node = Node(
                    id=file_node_id,
                    kind=NodeKind.FILE,
                    name=file_path.name,
                    qualname=rel,
                    file=rel,
                    line_start=1,
                    line_end=0,
                    content_hash=content_hash,
                    language=language,
                    metadata={"size": file_path.stat().st_size},
                )
                self._store.upsert_node(file_node)
                stats.nodes_added += 1

                if extractor is not None:
                    nodes, edges = extractor.parse_file(
                        file_path, self._repo_root
                    )
                    self._store.upsert_nodes(nodes)
                    self._store.upsert_edges(edges)
                    stats.nodes_added += len(nodes)
                    stats.edges_added += len(edges)
                    stats.files_parsed += 1

            except Exception as exc:
                logger.warning("Error parsing %s: %s", rel, exc)
                stats.errors.append(f"{rel}: {exc}")

        now = datetime.now(tz=timezone.utc).isoformat()
        self._store.set_meta("last_build_time", now)
        git_sha = _get_git_sha(self._repo_root)
        if git_sha:
            self._store.set_meta("last_git_sha", git_sha)

        # Best-effort cross-file resolution of unresolved CALLS/IMPORTS edges.
        try:
            from codegraph.resolve import resolve_unresolved_edges
            rstats = resolve_unresolved_edges(self._store)
            self._store.set_meta(
                "last_resolve",
                f"{rstats.resolved}/{rstats.inspected} resolved",
            )
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("resolver failed: %s", exc)
            stats.errors.append(f"resolver: {exc}")

        return stats

    def _walk_repo(self, spec: Any) -> list[Path]:
        result: list[Path] = []
        for file_path in sorted(self._repo_root.rglob("*")):
            if not file_path.is_file():
                continue
            try:
                rel = file_path.relative_to(self._repo_root).as_posix()
            except ValueError:
                continue
            if spec.match_file(rel):
                continue
            parts = Path(rel).parts
            if any(part in _IGNORE_DIRS for part in parts[:-1]):
                continue
            result.append(file_path)
        return result
