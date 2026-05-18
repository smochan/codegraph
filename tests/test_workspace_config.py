"""Unit tests for ``codegraph.workspace.config``.

Covers load/save round-trip, env-var override of the workspace path,
WorkspaceConfig helpers, and error handling for malformed YAML.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from codegraph.workspace.config import (
    WorkspaceConfig,
    WorkspaceRepo,
    load_workspace,
    resolve_workspace_path,
    save_workspace,
)


def test_resolve_workspace_path_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CODEGRAPH_WORKSPACE_FILE", raising=False)
    assert resolve_workspace_path() == Path.home() / ".codegraph" / "workspace.yml"


def test_resolve_workspace_path_env_override(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    override = tmp_path / "alt.yml"
    monkeypatch.setenv("CODEGRAPH_WORKSPACE_FILE", str(override))
    assert resolve_workspace_path() == override


def test_load_missing_file_returns_empty(tmp_path: Path) -> None:
    cfg = load_workspace(tmp_path / "nope.yml")
    assert isinstance(cfg, WorkspaceConfig)
    assert cfg.repos == []
    assert cfg.version == 1


def test_save_and_load_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "workspace.yml"
    cfg = WorkspaceConfig(
        repos=[
            WorkspaceRepo(path="/tmp/foo", name="foo"),
            WorkspaceRepo(path="/tmp/bar"),
        ]
    )
    save_workspace(cfg, path)
    assert path.exists()

    loaded = load_workspace(path)
    assert len(loaded.repos) == 2
    assert loaded.repos[0].path == "/tmp/foo"
    assert loaded.repos[0].name == "foo"
    assert loaded.repos[1].path == "/tmp/bar"
    assert loaded.repos[1].name is None
    assert loaded.repos[1].display_name == "bar"


def test_save_creates_parent_dirs(tmp_path: Path) -> None:
    path = tmp_path / "deep" / "nested" / "workspace.yml"
    save_workspace(WorkspaceConfig(), path)
    assert path.exists()


def test_has_repo_resolves_path(tmp_path: Path) -> None:
    real = tmp_path / "real"
    real.mkdir()
    cfg = WorkspaceConfig(repos=[WorkspaceRepo(path=str(real))])
    assert cfg.has_repo(real) is True
    assert cfg.has_repo(tmp_path / "other") is False


def test_remove_repo(tmp_path: Path) -> None:
    a = tmp_path / "a"
    b = tmp_path / "b"
    a.mkdir()
    b.mkdir()
    cfg = WorkspaceConfig(
        repos=[WorkspaceRepo(path=str(a)), WorkspaceRepo(path=str(b))]
    )
    assert cfg.remove_repo(a) is True
    assert len(cfg.repos) == 1
    assert cfg.repos[0].path == str(b)
    # Removing again is a no-op
    assert cfg.remove_repo(a) is False
    assert len(cfg.repos) == 1


def test_malformed_yaml_raises(tmp_path: Path) -> None:
    bad = tmp_path / "bad.yml"
    bad.write_text("not: [valid yaml\n")
    with pytest.raises(ValueError, match="Invalid YAML"):
        load_workspace(bad)


def test_non_mapping_yaml_raises(tmp_path: Path) -> None:
    not_dict = tmp_path / "list.yml"
    not_dict.write_text("- just\n- a\n- list\n")
    with pytest.raises(ValueError, match="must be a mapping"):
        load_workspace(not_dict)


def test_workspace_repo_display_name() -> None:
    with_name = WorkspaceRepo(path="/x/y/z", name="custom")
    assert with_name.display_name == "custom"
    no_name = WorkspaceRepo(path="/x/y/z")
    assert no_name.display_name == "z"
