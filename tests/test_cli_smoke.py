"""Smoke tests: CLI is wired and stubs respond."""

from __future__ import annotations

from typer.testing import CliRunner

from codegraph import __version__
from codegraph.cli import app

runner = CliRunner()


def test_version_flag() -> None:
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert __version__ in result.stdout


def test_help_lists_subcommands() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    for cmd in ("init", "build", "status", "viz", "analyze", "review", "query", "mcp"):
        assert cmd in result.stdout


def test_init_stub() -> None:
    result = runner.invoke(app, ["init"])
    assert result.exit_code == 0
    assert "init" in result.stdout
