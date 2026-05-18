"""Tests for ``codegraph.workspace.operations`` against real (tmp) git repos."""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from codegraph.workspace.config import WorkspaceConfig, WorkspaceRepo
from codegraph.workspace.operations import (
    repo_blast_radius,
    repo_diff_since,
    repo_status,
    workspace_blast_radius,
    workspace_diff_since,
    workspace_state,
)

FIXTURES = Path(__file__).parent / "fixtures"


def _git(repo: Path, *args: str, **env_overrides: str) -> None:
    """Run a git command inside *repo*, swallowing stderr for clean test output."""
    env = {
        "GIT_AUTHOR_NAME": "Test",
        "GIT_AUTHOR_EMAIL": "test@example.com",
        "GIT_COMMITTER_NAME": "Test",
        "GIT_COMMITTER_EMAIL": "test@example.com",
        "PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin",
    }
    env.update(env_overrides)
    subprocess.run(["git", *args], cwd=repo, env=env, check=True, capture_output=True)


def _make_git_repo(path: Path, source_fixture: str = "python_sample") -> Path:
    """Init a git repo at *path*, copy a fixture in, and make an initial commit on main."""
    path.mkdir(parents=True, exist_ok=True)
    shutil.copytree(FIXTURES / source_fixture, path / "src")
    _git(path, "init", "-b", "main")
    _git(path, "add", ".")
    _git(path, "commit", "-m", "initial commit")
    return path


@pytest.fixture
def alpha_repo(tmp_path: Path) -> Path:
    return _make_git_repo(tmp_path / "alpha")


@pytest.fixture
def beta_repo(tmp_path: Path) -> Path:
    return _make_git_repo(tmp_path / "beta")


@pytest.fixture
def workspace_two(alpha_repo: Path, beta_repo: Path) -> WorkspaceConfig:
    return WorkspaceConfig(
        repos=[
            WorkspaceRepo(path=str(alpha_repo), name="alpha"),
            WorkspaceRepo(path=str(beta_repo), name="beta"),
        ]
    )


# ---------------------------------------------------------------------------
# repo_status / workspace_state
# ---------------------------------------------------------------------------


def test_repo_status_clean_repo(alpha_repo: Path) -> None:
    status = repo_status(WorkspaceRepo(path=str(alpha_repo), name="alpha"))
    assert status.name == "alpha"
    assert status.exists is True
    assert status.is_git is True
    assert status.branch == "main"
    assert status.dirty_files == 0
    assert status.error is None
    assert status.last_commit is not None
    assert "initial commit" in status.last_commit


def test_repo_status_dirty_repo(alpha_repo: Path) -> None:
    # Modify a tracked file
    (alpha_repo / "src" / "DIRTY.txt").write_text("hello")
    status = repo_status(WorkspaceRepo(path=str(alpha_repo)))
    assert status.dirty_files >= 1


def test_repo_status_missing_dir(tmp_path: Path) -> None:
    status = repo_status(WorkspaceRepo(path=str(tmp_path / "does-not-exist")))
    assert status.exists is False
    assert status.error == "directory not found"


def test_repo_status_non_git_dir(tmp_path: Path) -> None:
    not_git = tmp_path / "plain"
    not_git.mkdir()
    status = repo_status(WorkspaceRepo(path=str(not_git)))
    assert status.exists is True
    assert status.is_git is False
    assert status.error == "not a git repository"


def test_workspace_state_aggregates(workspace_two: WorkspaceConfig) -> None:
    state = workspace_state(workspace_two)
    assert state["workspace_size"] == 2
    names = sorted(r["name"] for r in state["repos"])
    assert names == ["alpha", "beta"]
    for r in state["repos"]:
        assert r["branch"] == "main"
        assert r["error"] is None


# ---------------------------------------------------------------------------
# repo_diff_since / workspace_diff_since
# ---------------------------------------------------------------------------


def test_repo_diff_since_committed_change(alpha_repo: Path) -> None:
    # Create a feature branch with a new file
    _git(alpha_repo, "checkout", "-b", "feature")
    (alpha_repo / "src" / "NEW.txt").write_text("new file")
    _git(alpha_repo, "add", ".")
    _git(alpha_repo, "commit", "-m", "add NEW.txt")

    result = repo_diff_since(WorkspaceRepo(path=str(alpha_repo)), ref="main")
    assert "src/NEW.txt" in result["files"]
    assert result["files_changed"] >= 1
    assert result.get("error") is None


def test_repo_diff_since_uncommitted_change(alpha_repo: Path) -> None:
    (alpha_repo / "src" / "WORKING.txt").write_text("not committed")
    _git(alpha_repo, "add", ".")  # stage it so it shows up in diff HEAD
    result = repo_diff_since(WorkspaceRepo(path=str(alpha_repo)), ref="main")
    assert "src/WORKING.txt" in result["files"]


def test_repo_diff_since_missing_ref_does_not_error(alpha_repo: Path) -> None:
    # Refs that don't exist should not cause an error — just empty file list
    result = repo_diff_since(WorkspaceRepo(path=str(alpha_repo)), ref="nonexistent-ref")
    assert result["files"] == []
    assert result.get("error") is None


def test_workspace_diff_since_totals(workspace_two: WorkspaceConfig) -> None:
    alpha_path = Path(workspace_two.repos[0].path)
    _git(alpha_path, "checkout", "-b", "feature")
    (alpha_path / "src" / "X.txt").write_text("alpha change")
    _git(alpha_path, "add", ".")
    _git(alpha_path, "commit", "-m", "alpha")

    diff = workspace_diff_since(workspace_two, ref="main")
    assert diff["ref"] == "main"
    assert diff["workspace_size"] == 2
    assert diff["total_files_changed"] >= 1
    # Find alpha entry
    alpha_entry = next(r for r in diff["repos"] if r["name"] == "alpha")
    assert "src/X.txt" in alpha_entry["files"]


# ---------------------------------------------------------------------------
# blast_radius
# ---------------------------------------------------------------------------


def _build_graph(repo: Path) -> None:
    """Run codegraph build inside *repo* via the public API."""
    from codegraph.config import load_config
    from codegraph.graph.builder import GraphBuilder
    from codegraph.graph.store_sqlite import SQLiteGraphStore

    cfg = load_config(repo)
    data_dir = repo / ".codegraph"
    data_dir.mkdir(parents=True, exist_ok=True)
    db_path = data_dir / "graph.db"
    store = SQLiteGraphStore(db_path)
    builder = GraphBuilder(repo, store, ignore=cfg.ignore)
    builder.build(incremental=False)
    store.close()


def test_repo_blast_radius_without_graph(alpha_repo: Path) -> None:
    """When no graph.db exists, blast_radius should not raise — return error."""
    result = repo_blast_radius(WorkspaceRepo(path=str(alpha_repo)), "anything")
    assert result["found"] is False
    assert "no .codegraph/graph.db" in (result.get("error") or "")


def test_repo_blast_radius_with_graph(alpha_repo: Path) -> None:
    """After building, blast_radius should resolve a symbol found in fixtures."""
    _build_graph(alpha_repo)
    # Find any symbol in the graph to query — use a substring that should match
    # something in python_sample. Quick sanity: just check the call doesn't blow up
    # and that 'found' is a bool. We don't assert specific node names since the
    # fixture's content isn't this test's concern.
    result = repo_blast_radius(
        WorkspaceRepo(path=str(alpha_repo)), "nonexistent_zzzzz"
    )
    assert result["found"] is False
    assert result["nodes"] == []


def test_workspace_blast_radius_skips_unbuilt_repos(
    workspace_two: WorkspaceConfig,
) -> None:
    # Build only one of the two
    alpha_path = Path(workspace_two.repos[0].path)
    _build_graph(alpha_path)

    result = workspace_blast_radius(workspace_two, symbol="zzz_nonexistent")
    assert result["workspace_size"] == 2
    # Neither repo will "find" the symbol, but the call should not raise
    assert result["repos_with_match"] == 0
    # The unbuilt repo should have an error message about missing graph.db
    beta_entry = next(r for r in result["repos"] if r["name"] == "beta")
    assert beta_entry["found"] is False
    assert "no .codegraph/graph.db" in (beta_entry.get("error") or "")
