"""Smoke tests: CLI is wired and stubs respond."""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from codegraph import __version__
from codegraph.cli import app

runner = CliRunner()


def test_version_flag() -> None:
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert __version__ in result.stdout


def test_version_matches_package_metadata() -> None:
    """Regression: __version__ must auto-sync with pyproject via importlib.metadata.

    Catches the failure mode where someone re-hardcodes the version string and
    it drifts from the actual published wheel — which is exactly what bit us
    pre-0.1.0rc2 (codegraph.__version__ was "0.0.1" while the published wheel
    was "0.1.0rc1").
    """
    from importlib.metadata import version as _pkg_version
    assert __version__ == _pkg_version("polycodegraph")


def test_help_lists_subcommands() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    for cmd in ("init", "build", "status", "viz", "analyze", "review", "query", "mcp"):
        assert cmd in result.stdout


def test_init_non_interactive_smoke(tmp_path: Path) -> None:
    import os

    orig = os.getcwd()
    os.chdir(tmp_path)
    try:
        result = runner.invoke(app, ["init", "--non-interactive"])
    finally:
        os.chdir(orig)
    assert result.exit_code == 0
    assert (tmp_path / ".codegraph.yml").exists()
