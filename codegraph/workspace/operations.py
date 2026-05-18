"""Pure functions for workspace operations — reused by CLI and MCP server.

All functions take a :class:`WorkspaceConfig` (or a list of
:class:`WorkspaceRepo`) and return JSON-serializable dicts. The MCP layer
just JSON-dumps the return values; the CLI renders them via Rich.

These functions are intentionally side-effect-free except for opening
SQLite connections to per-repo graph DBs (which they close before returning).
"""
from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from codegraph.workspace.config import WorkspaceConfig, WorkspaceRepo

# ---------------------------------------------------------------------------
# Repo health / state
# ---------------------------------------------------------------------------


@dataclass
class RepoStatus:
    """Snapshot of a single registered repo's filesystem + git state."""

    name: str
    path: str
    exists: bool
    is_git: bool
    has_graph: bool
    branch: str | None = None
    dirty_files: int = 0
    last_commit: str | None = None
    last_commit_at: str | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "path": self.path,
            "exists": self.exists,
            "is_git": self.is_git,
            "has_graph": self.has_graph,
            "branch": self.branch,
            "dirty_files": self.dirty_files,
            "last_commit": self.last_commit,
            "last_commit_at": self.last_commit_at,
            "error": self.error,
        }


def _git(repo_path: Path, *args: str, timeout: int = 10) -> str:
    """Run a git command inside *repo_path* and return stripped stdout.

    Raises ``subprocess.CalledProcessError`` on non-zero exit.
    """
    result = subprocess.run(
        ["git", *args],
        cwd=repo_path,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=True,
    )
    return result.stdout.strip()


def repo_status(repo: WorkspaceRepo) -> RepoStatus:
    """Compute the current status of a single registered repo.

    Never raises — errors are captured into the ``error`` field so workspace-wide
    operations can show partial results for healthy repos.
    """
    path = Path(repo.path).expanduser()
    name = repo.display_name

    status = RepoStatus(
        name=name,
        path=str(path),
        exists=path.exists(),
        is_git=False,
        has_graph=False,
    )

    if not status.exists:
        status.error = "directory not found"
        return status

    status.is_git = (path / ".git").exists()
    status.has_graph = (path / ".codegraph" / "graph.db").exists()

    if not status.is_git:
        status.error = "not a git repository"
        return status

    try:
        status.branch = _git(path, "rev-parse", "--abbrev-ref", "HEAD") or None
        porcelain = _git(path, "status", "--porcelain")
        status.dirty_files = (
            len([line for line in porcelain.splitlines() if line.strip()])
            if porcelain
            else 0
        )
        status.last_commit = _git(path, "log", "-1", "--pretty=%h %s")
        status.last_commit_at = _git(path, "log", "-1", "--pretty=%cI")
    except subprocess.CalledProcessError as exc:
        status.error = (
            f"git command failed: {' '.join(exc.cmd)} "
            f"(exit {exc.returncode}): {exc.stderr.strip()[:200]}"
        )
    except subprocess.TimeoutExpired:
        status.error = "git command timed out"
    except FileNotFoundError:
        status.error = "git binary not found on PATH"

    return status


def workspace_state(cfg: WorkspaceConfig) -> dict[str, Any]:
    """Return git + graph state for every registered repo."""
    repos = [repo_status(r).to_dict() for r in cfg.repos]
    return {
        "workspace_size": len(repos),
        "repos": repos,
    }


# ---------------------------------------------------------------------------
# Cross-repo diff
# ---------------------------------------------------------------------------


def _diff_files(repo_path: Path, ref: str) -> list[str]:
    """List files changed in repo_path since *ref* (committed + working tree).

    Combines ``git diff --name-only <ref>...HEAD`` (committed changes since the
    merge-base with *ref*) with ``git diff --name-only HEAD`` (uncommitted).
    """
    files: set[str] = set()
    try:
        committed = _git(repo_path, "diff", "--name-only", f"{ref}...HEAD")
        if committed:
            files.update(line for line in committed.splitlines() if line.strip())
    except subprocess.CalledProcessError:
        # ref may not exist in this repo — skip silently
        pass
    try:
        working = _git(repo_path, "diff", "--name-only", "HEAD")
        if working:
            files.update(line for line in working.splitlines() if line.strip())
    except subprocess.CalledProcessError:
        pass
    return sorted(files)


def repo_diff_since(repo: WorkspaceRepo, ref: str) -> dict[str, Any]:
    """List changed files in one repo since *ref*."""
    path = Path(repo.path).expanduser()
    name = repo.display_name

    if not path.exists():
        return {"name": name, "path": str(path), "error": "directory not found", "files": []}
    if not (path / ".git").exists():
        return {"name": name, "path": str(path), "error": "not a git repository", "files": []}
    try:
        files = _diff_files(path, ref)
    except FileNotFoundError:
        return {
            "name": name,
            "path": str(path),
            "error": "git binary not found on PATH",
            "files": [],
        }
    return {
        "name": name,
        "path": str(path),
        "ref": ref,
        "files": files,
        "files_changed": len(files),
    }


def workspace_diff_since(cfg: WorkspaceConfig, ref: str = "main") -> dict[str, Any]:
    """List files changed across every registered repo since *ref*."""
    repos = [repo_diff_since(r, ref) for r in cfg.repos]
    total = sum(int(r.get("files_changed", 0)) for r in repos)
    return {
        "ref": ref,
        "workspace_size": len(repos),
        "total_files_changed": total,
        "repos": repos,
    }


# ---------------------------------------------------------------------------
# Cross-repo blast radius
# ---------------------------------------------------------------------------


def _open_repo_graph(repo: WorkspaceRepo) -> Any | None:
    """Load a repo's graph as a NetworkX MultiDiGraph, or None if unavailable."""
    db_path = Path(repo.path).expanduser() / ".codegraph" / "graph.db"
    if not db_path.exists():
        return None
    # Lazy imports keep CLI startup fast and avoid pulling these into every test.
    from codegraph.graph.store_networkx import to_digraph
    from codegraph.graph.store_sqlite import SQLiteGraphStore

    store = SQLiteGraphStore(db_path)
    try:
        return to_digraph(store)
    finally:
        store.close()


def repo_blast_radius(
    repo: WorkspaceRepo, symbol: str, depth: int | None = None
) -> dict[str, Any]:
    """Compute blast radius for *symbol* in one repo, returning a JSON-safe dict."""
    name = repo.display_name
    graph = _open_repo_graph(repo)
    if graph is None:
        return {
            "name": name,
            "path": str(Path(repo.path).expanduser()),
            "error": "no .codegraph/graph.db (run `codegraph build` first)",
            "found": False,
            "nodes": [],
            "files": [],
        }

    # Resolve symbol to a node ID — qualname substring match (case-insensitive),
    # mirrors `find_symbol`'s behavior so users can pass either a full qualname
    # or an unambiguous substring.
    sym = symbol.lower()
    target_id: str | None = None
    for nid, attrs in graph.nodes(data=True):
        qualname = str(attrs.get("qualname") or nid)
        if qualname.lower() == sym or qualname == symbol:
            target_id = nid
            break
    if target_id is None:
        for nid, attrs in graph.nodes(data=True):
            qualname = str(attrs.get("qualname") or nid)
            if sym in qualname.lower():
                target_id = nid
                break
    if target_id is None:
        return {
            "name": name,
            "path": str(Path(repo.path).expanduser()),
            "found": False,
            "nodes": [],
            "files": [],
        }

    from codegraph.analysis.blast_radius import blast_radius as _blast

    result = _blast(graph, target_id, depth=depth)
    return {
        "name": name,
        "path": str(Path(repo.path).expanduser()),
        "found": True,
        "target": str(target_id),
        "target_qualname": str(
            graph.nodes[target_id].get("qualname") or target_id
        ),
        "nodes": list(result.nodes),
        "node_count": len(result.nodes),
        "files": sorted(result.files),
        "file_count": len(result.files),
        "test_nodes": list(result.test_nodes),
    }


def workspace_blast_radius(
    cfg: WorkspaceConfig, symbol: str, depth: int | None = None
) -> dict[str, Any]:
    """Compute blast radius for *symbol* across every registered repo."""
    per_repo = [repo_blast_radius(r, symbol, depth=depth) for r in cfg.repos]
    hits = [r for r in per_repo if r.get("found")]
    total_nodes = sum(int(r.get("node_count", 0)) for r in per_repo)
    total_files = sum(int(r.get("file_count", 0)) for r in per_repo)
    return {
        "symbol": symbol,
        "depth": depth,
        "workspace_size": len(per_repo),
        "repos_with_match": len(hits),
        "total_nodes": total_nodes,
        "total_files": total_files,
        "repos": per_repo,
    }
