"""Tests for the three workspace MCP tool handlers in ``codegraph.mcp_server.server``.

Calls handlers directly (bypassing the stdio transport) to verify the JSON shape.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from codegraph.mcp_server.server import (
    _handle_workspace_blast_radius,
    _handle_workspace_diff_since,
    _handle_workspace_state,
)
from codegraph.workspace.config import (
    WorkspaceConfig,
    WorkspaceRepo,
    save_workspace,
)

FIXTURES = Path(__file__).parent / "fixtures"


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


@pytest.fixture
def workspace_with_two_repos(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[Path, Path]:
    a = _make_git_repo(tmp_path / "alpha")
    b = _make_git_repo(tmp_path / "beta")
    workspace_path = tmp_path / "workspace.yml"
    save_workspace(
        WorkspaceConfig(
            repos=[
                WorkspaceRepo(path=str(a), name="alpha"),
                WorkspaceRepo(path=str(b), name="beta"),
            ]
        ),
        workspace_path,
    )
    monkeypatch.setenv("CODEGRAPH_WORKSPACE_FILE", str(workspace_path))
    return a, b


def test_workspace_state_handler(workspace_with_two_repos: tuple[Path, Path]) -> None:
    result = _handle_workspace_state(graph=None, args={})  # type: ignore[arg-type]
    assert isinstance(result, dict)
    assert result["workspace_size"] == 2
    names = sorted(r["name"] for r in result["repos"])
    assert names == ["alpha", "beta"]
    for repo in result["repos"]:
        assert repo["branch"] == "main"
        assert repo["error"] is None


def test_workspace_diff_since_handler(
    workspace_with_two_repos: tuple[Path, Path],
) -> None:
    alpha, _ = workspace_with_two_repos
    # Create a divergence
    env = {
        "GIT_AUTHOR_NAME": "Test",
        "GIT_AUTHOR_EMAIL": "test@example.com",
        "GIT_COMMITTER_NAME": "Test",
        "GIT_COMMITTER_EMAIL": "test@example.com",
        "PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin",
    }
    for cmd in (
        ["checkout", "-b", "feature"],
    ):
        subprocess.run(["git", *cmd], cwd=alpha, env=env, check=True, capture_output=True)
    (alpha / "src" / "FEATURE.txt").write_text("x")
    for cmd in (["add", "."], ["commit", "-m", "feat"]):
        subprocess.run(["git", *cmd], cwd=alpha, env=env, check=True, capture_output=True)

    result = _handle_workspace_diff_since(graph=None, args={"ref": "main"})  # type: ignore[arg-type]
    assert isinstance(result, dict)
    assert result["ref"] == "main"
    assert result["workspace_size"] == 2
    alpha_entry = next(r for r in result["repos"] if r["name"] == "alpha")
    assert "src/FEATURE.txt" in alpha_entry["files"]
    beta_entry = next(r for r in result["repos"] if r["name"] == "beta")
    assert beta_entry["files"] == []


def test_workspace_diff_since_defaults_ref_to_main(
    workspace_with_two_repos: tuple[Path, Path],
) -> None:
    result = _handle_workspace_diff_since(graph=None, args={})  # type: ignore[arg-type]
    assert result["ref"] == "main"


def test_workspace_blast_radius_handler_no_graph(
    workspace_with_two_repos: tuple[Path, Path],
) -> None:
    # Neither repo has been built — handler should still return the expected shape
    result = _handle_workspace_blast_radius(
        graph=None, args={"symbol": "anything"}  # type: ignore[arg-type]
    )
    assert isinstance(result, dict)
    assert result["symbol"] == "anything"
    assert result["workspace_size"] == 2
    assert result["repos_with_match"] == 0
    for repo in result["repos"]:
        assert repo["found"] is False
        assert "no .codegraph/graph.db" in (repo.get("error") or "")
