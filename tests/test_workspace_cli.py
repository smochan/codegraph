"""CLI integration tests for ``codegraph workspace ...`` commands."""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from codegraph.cli import app

runner = CliRunner()
FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def workspace_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Isolate the workspace file per test via the env override."""
    path = tmp_path / "workspace.yml"
    monkeypatch.setenv("CODEGRAPH_WORKSPACE_FILE", str(path))
    return path


def _make_git_repo(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    shutil.copytree(FIXTURES / "python_sample", path / "src")
    env = {
        "GIT_AUTHOR_NAME": "Test",
        "GIT_AUTHOR_EMAIL": "test@example.com",
        "GIT_COMMITTER_NAME": "Test",
        "GIT_COMMITTER_EMAIL": "test@example.com",
        "PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin",
    }
    for cmd in (
        ["init", "-b", "main"],
        ["add", "."],
        ["commit", "-m", "init"],
    ):
        subprocess.run(["git", *cmd], cwd=path, env=env, check=True, capture_output=True)
    return path


def test_init_creates_workspace(workspace_file: Path) -> None:
    result = runner.invoke(app, ["workspace", "init"], catch_exceptions=False)
    assert result.exit_code == 0
    assert workspace_file.exists()


def test_init_refuses_overwrite_without_force(workspace_file: Path) -> None:
    runner.invoke(app, ["workspace", "init"])
    result = runner.invoke(app, ["workspace", "init"], catch_exceptions=False)
    assert result.exit_code == 1
    # Normalize whitespace because Rich wraps long paths in narrow CI terminals
    assert "already exists" in " ".join(result.stdout.split())


def test_init_force_resets(workspace_file: Path, tmp_path: Path) -> None:
    runner.invoke(app, ["workspace", "init"])
    repo = _make_git_repo(tmp_path / "r")
    runner.invoke(app, ["workspace", "add", str(repo)])
    # Verify it's there
    list_before = runner.invoke(app, ["workspace", "list"])
    assert "r" in list_before.stdout
    # Force re-init
    result = runner.invoke(app, ["workspace", "init", "--force"], catch_exceptions=False)
    assert result.exit_code == 0
    list_after = runner.invoke(app, ["workspace", "list"])
    assert "No repositories" in list_after.stdout


def test_add_registers_repo(workspace_file: Path, tmp_path: Path) -> None:
    repo = _make_git_repo(tmp_path / "myrepo")
    result = runner.invoke(
        app, ["workspace", "add", str(repo)], catch_exceptions=False
    )
    assert result.exit_code == 0
    assert "added" in result.stdout.lower()


def test_add_validates_directory_exists(workspace_file: Path, tmp_path: Path) -> None:
    fake = tmp_path / "ghost"
    result = runner.invoke(
        app, ["workspace", "add", str(fake)], catch_exceptions=False
    )
    assert result.exit_code == 1
    # Normalize whitespace because Rich wraps long paths in narrow CI terminals
    assert "does not exist" in " ".join(result.stdout.split())


def test_add_is_idempotent(workspace_file: Path, tmp_path: Path) -> None:
    repo = _make_git_repo(tmp_path / "r")
    first = runner.invoke(app, ["workspace", "add", str(repo)])
    assert first.exit_code == 0
    second = runner.invoke(app, ["workspace", "add", str(repo)], catch_exceptions=False)
    assert second.exit_code == 0
    assert "already registered" in second.stdout


def test_remove_drops_repo(workspace_file: Path, tmp_path: Path) -> None:
    repo = _make_git_repo(tmp_path / "r")
    runner.invoke(app, ["workspace", "add", str(repo)])
    result = runner.invoke(
        app, ["workspace", "remove", str(repo)], catch_exceptions=False
    )
    assert result.exit_code == 0
    list_result = runner.invoke(app, ["workspace", "list"])
    assert "No repositories" in list_result.stdout


def test_remove_unknown_repo_errors(workspace_file: Path, tmp_path: Path) -> None:
    runner.invoke(app, ["workspace", "init"])
    fake = tmp_path / "neverregistered"
    result = runner.invoke(
        app, ["workspace", "remove", str(fake)], catch_exceptions=False
    )
    assert result.exit_code == 1


def test_list_shows_registered_repos(workspace_file: Path, tmp_path: Path) -> None:
    a = _make_git_repo(tmp_path / "alpha")
    b = _make_git_repo(tmp_path / "beta")
    runner.invoke(app, ["workspace", "add", str(a)])
    runner.invoke(app, ["workspace", "add", str(b)])
    result = runner.invoke(app, ["workspace", "list"], catch_exceptions=False)
    assert result.exit_code == 0
    assert "alpha" in result.stdout
    assert "beta" in result.stdout


def test_list_empty_workspace(workspace_file: Path) -> None:
    result = runner.invoke(app, ["workspace", "list"], catch_exceptions=False)
    assert result.exit_code == 0
    assert "No repositories" in " ".join(result.stdout.split())


def test_status_shows_branch(workspace_file: Path, tmp_path: Path) -> None:
    repo = _make_git_repo(tmp_path / "r")
    runner.invoke(app, ["workspace", "add", str(repo)])
    result = runner.invoke(app, ["workspace", "status"], catch_exceptions=False)
    assert result.exit_code == 0
    assert "main" in result.stdout


def test_sync_builds_graphs(workspace_file: Path, tmp_path: Path) -> None:
    repo = _make_git_repo(tmp_path / "r")
    runner.invoke(app, ["workspace", "add", str(repo)])
    result = runner.invoke(app, ["workspace", "sync"], catch_exceptions=False)
    assert result.exit_code == 0
    assert (repo / ".codegraph" / "graph.db").exists()
    assert "ok" in result.stdout.lower()


def test_sync_only_filters_to_one_repo(
    workspace_file: Path, tmp_path: Path
) -> None:
    a = _make_git_repo(tmp_path / "alpha")
    b = _make_git_repo(tmp_path / "beta")
    runner.invoke(app, ["workspace", "add", str(a)])
    runner.invoke(app, ["workspace", "add", str(b)])
    result = runner.invoke(
        app, ["workspace", "sync", "--only", "alpha"], catch_exceptions=False
    )
    assert result.exit_code == 0
    # Only alpha got a graph
    assert (a / ".codegraph" / "graph.db").exists()
    assert not (b / ".codegraph" / "graph.db").exists()
