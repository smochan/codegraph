"""Tests for `_write_project_mcp_json` (item #1 of v0.1.2 backlog).

The 0.1.1 fix wrote `.mcp.json` but used a bare `codegraph` command with
no `--db` and no `cwd`. 0.1.2 fixes that to use an absolute binary path,
an explicit `--db` pointing at `.codegraph/graph.db`, and `cwd` set to
the repo root. Pre-0.1.2 default entries are migrated forward in place;
customised entries are left alone.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from codegraph.cli import (
    _build_mcp_entry,
    _is_default_codegraph_entry,
    _resolve_codegraph_binary,
    _write_project_mcp_json,
)


def test_build_mcp_entry_has_absolute_path_db_and_cwd(tmp_path: Path) -> None:
    entry = _build_mcp_entry(tmp_path)
    assert isinstance(entry["command"], str)
    # Either an absolute resolved path or the bare fallback. The path-aware
    # branch is exercised by test_resolve_codegraph_binary_prefers_sibling.
    args = entry["args"]
    assert isinstance(args, list)
    assert args[0] == "mcp"
    assert args[1] == "serve"
    assert "--db" in args
    db_idx = args.index("--db") + 1
    assert args[db_idx] == str(tmp_path / ".codegraph" / "graph.db")
    assert entry["cwd"] == str(tmp_path)


def test_resolve_codegraph_binary_prefers_sibling(
    tmp_path: Path, monkeypatch
) -> None:
    fake_venv = tmp_path / "venv" / "bin"
    fake_venv.mkdir(parents=True)
    fake_py = fake_venv / "python"
    fake_py.write_text("")
    fake_cg = fake_venv / "codegraph"
    fake_cg.write_text("")
    monkeypatch.setattr(sys, "executable", str(fake_py))
    assert _resolve_codegraph_binary() == str(fake_cg)


def test_is_default_codegraph_entry_detects_old_shape() -> None:
    assert _is_default_codegraph_entry(
        {"command": "codegraph", "args": ["mcp", "serve"]}
    )
    # Customised: different binary
    assert not _is_default_codegraph_entry(
        {"command": "/opt/cg/bin/codegraph", "args": ["mcp", "serve"]}
    )
    # Customised: extra cwd
    assert not _is_default_codegraph_entry(
        {"command": "codegraph", "args": ["mcp", "serve"], "cwd": "/repo"}
    )
    # Customised: different args
    assert not _is_default_codegraph_entry(
        {"command": "codegraph", "args": ["mcp", "serve", "--db", "x"]}
    )
    assert not _is_default_codegraph_entry("not-a-dict")


def test_write_mcp_json_fresh(tmp_path: Path) -> None:
    state = _write_project_mcp_json(tmp_path)
    assert state == "created"
    data = json.loads((tmp_path / ".mcp.json").read_text())
    entry = data["mcpServers"]["codegraph"]
    assert entry["cwd"] == str(tmp_path)
    assert "--db" in entry["args"]


def test_write_mcp_json_migrates_pre_012_default(tmp_path: Path) -> None:
    (tmp_path / ".mcp.json").write_text(
        json.dumps(
            {"mcpServers": {"codegraph": {"command": "codegraph", "args": ["mcp", "serve"]}}}
        )
    )
    state = _write_project_mcp_json(tmp_path)
    assert state == "migrated"
    entry = json.loads((tmp_path / ".mcp.json").read_text())["mcpServers"]["codegraph"]
    assert entry["cwd"] == str(tmp_path)
    assert "--db" in entry["args"]


def test_write_mcp_json_preserves_customised_entry(tmp_path: Path) -> None:
    custom = {
        "command": "/opt/cg/bin/codegraph",
        "args": ["mcp", "serve", "--verbose"],
        "env": {"FOO": "bar"},
    }
    (tmp_path / ".mcp.json").write_text(
        json.dumps({"mcpServers": {"codegraph": custom, "other": {"command": "x"}}})
    )
    state = _write_project_mcp_json(tmp_path)
    assert state == "already-present"
    data = json.loads((tmp_path / ".mcp.json").read_text())
    assert data["mcpServers"]["codegraph"] == custom
    assert data["mcpServers"]["other"] == {"command": "x"}


def test_write_mcp_json_merges_when_codegraph_missing(tmp_path: Path) -> None:
    (tmp_path / ".mcp.json").write_text(
        json.dumps({"mcpServers": {"other": {"command": "x"}}})
    )
    state = _write_project_mcp_json(tmp_path)
    assert state == "merged"
    data = json.loads((tmp_path / ".mcp.json").read_text())
    assert "codegraph" in data["mcpServers"]
    assert data["mcpServers"]["other"] == {"command": "x"}
