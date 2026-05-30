"""Tests for `_write_agent_guidance` (v0.1.2 #4).

Without a CLAUDE.md / AGENTS.md hint, coding agents default to grep
even when polycodegraph's MCP server is registered. `codegraph init`
now writes a section into those files; behaviour mirrors the
`.mcp.json` writer — create, append, or leave alone.
"""
from __future__ import annotations

from pathlib import Path

from codegraph.cli import _AGENT_GUIDANCE_HEADER, _write_agent_guidance


def test_creates_fresh_file(tmp_path: Path) -> None:
    state = _write_agent_guidance(tmp_path, "CLAUDE.md")
    assert state == "created"
    content = (tmp_path / "CLAUDE.md").read_text()
    assert _AGENT_GUIDANCE_HEADER in content
    assert "mcp__codegraph__find_symbol" in content


def test_appends_to_existing_file_without_section(tmp_path: Path) -> None:
    (tmp_path / "CLAUDE.md").write_text("# Project rules\n\nUse spaces.\n")
    state = _write_agent_guidance(tmp_path, "CLAUDE.md")
    assert state == "appended"
    content = (tmp_path / "CLAUDE.md").read_text()
    assert "Use spaces." in content
    assert _AGENT_GUIDANCE_HEADER in content
    # Section should be after the original content, separated by blank line.
    assert content.startswith("# Project rules")


def test_leaves_alone_when_section_already_present(tmp_path: Path) -> None:
    original = (
        "# Existing\n\n"
        f"{_AGENT_GUIDANCE_HEADER}\n\nUser-tweaked content here.\n"
    )
    (tmp_path / "AGENTS.md").write_text(original)
    state = _write_agent_guidance(tmp_path, "AGENTS.md")
    assert state == "already-present"
    assert (tmp_path / "AGENTS.md").read_text() == original


def test_appends_with_trailing_newline_when_existing_lacks_one(tmp_path: Path) -> None:
    (tmp_path / "CLAUDE.md").write_text("no trailing newline")
    state = _write_agent_guidance(tmp_path, "CLAUDE.md")
    assert state == "appended"
    content = (tmp_path / "CLAUDE.md").read_text()
    # Existing content + newline gap + section.
    assert content.startswith("no trailing newline\n")
    assert _AGENT_GUIDANCE_HEADER in content
