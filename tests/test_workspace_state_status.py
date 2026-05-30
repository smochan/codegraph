"""Tests for `workspace_state` status field (v0.1.2 #9)."""
from __future__ import annotations

from pathlib import Path

import yaml

from codegraph.mcp_server.server import _handle_workspace_state


def test_workspace_not_configured_when_file_missing(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv(
        "CODEGRAPH_WORKSPACE_FILE", str(tmp_path / "nope" / "workspace.yml")
    )
    result = _handle_workspace_state(None, {})
    assert result["status"] == "workspace_not_configured"
    assert "codegraph workspace init" in result["message"]
    assert "local-graph MCP tools" in result["message"]
    assert result["workspace_size"] == 0
    assert result["repos"] == []


def test_workspace_empty_when_file_exists_with_no_repos(
    tmp_path: Path, monkeypatch
) -> None:
    f = tmp_path / "workspace.yml"
    f.write_text(yaml.dump({"repos": []}))
    monkeypatch.setenv("CODEGRAPH_WORKSPACE_FILE", str(f))
    result = _handle_workspace_state(None, {})
    assert result["status"] == "workspace_empty"
    assert result["workspace_size"] == 0


def test_workspace_ok_when_repos_present(tmp_path: Path, monkeypatch) -> None:
    repo = tmp_path / "myrepo"
    repo.mkdir()
    f = tmp_path / "workspace.yml"
    f.write_text(yaml.dump({"repos": [{"path": str(repo), "name": "myrepo"}]}))
    monkeypatch.setenv("CODEGRAPH_WORKSPACE_FILE", str(f))
    result = _handle_workspace_state(None, {})
    assert result["status"] == "ok"
    assert result["workspace_size"] == 1
