"""CLI tests for `codegraph viz`."""
from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest
from typer.testing import CliRunner

from codegraph.cli import app

runner = CliRunner()
FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def built_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    shutil.copytree(FIXTURES / "python_sample", repo / "pkg")
    orig = os.getcwd()
    os.chdir(repo)
    try:
        runner.invoke(app, ["init", "--non-interactive"], catch_exceptions=False)
        runner.invoke(app, ["build"], catch_exceptions=False)
    finally:
        os.chdir(orig)
    return repo


def _run(repo: Path, args: list[str]) -> object:
    orig = os.getcwd()
    os.chdir(repo)
    try:
        return runner.invoke(app, args, catch_exceptions=False)
    finally:
        os.chdir(orig)


def test_viz_mermaid_default(built_repo: Path) -> None:
    result = _run(built_repo, ["viz"])
    assert result.exit_code == 0  # type: ignore[attr-defined]
    assert "flowchart LR" in result.stdout  # type: ignore[attr-defined]


def test_viz_html_writes_file(built_repo: Path) -> None:
    out = built_repo / "graph.html"
    result = _run(built_repo, ["viz", "--out", "html", "--output", str(out)])
    assert result.exit_code == 0  # type: ignore[attr-defined]
    assert out.exists()
    assert "<html" in out.read_text().lower()


def test_viz_html_default_path(built_repo: Path) -> None:
    result = _run(built_repo, ["viz", "--out", "html"])
    assert result.exit_code == 0  # type: ignore[attr-defined]
    assert (built_repo / ".codegraph" / "graph.html").exists()


def test_viz_unknown_format(built_repo: Path) -> None:
    result = _run(built_repo, ["viz", "--out", "bogus"])
    assert result.exit_code != 0  # type: ignore[attr-defined]
