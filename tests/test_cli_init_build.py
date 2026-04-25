"""CLI integration tests: init, build, status."""
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
def tmp_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    shutil.copytree(FIXTURES / "python_sample", repo / "src")
    return repo


def _run_in(repo: Path, args: list[str]) -> object:
    orig = os.getcwd()
    os.chdir(repo)
    try:
        return runner.invoke(app, args, catch_exceptions=False)
    finally:
        os.chdir(orig)


def test_init_non_interactive(tmp_repo: Path) -> None:
    result = _run_in(tmp_repo, ["init", "--non-interactive"])
    assert result.exit_code == 0  # type: ignore[attr-defined]
    assert (tmp_repo / ".codegraph.yml").exists()


def test_build_after_init(tmp_repo: Path) -> None:
    _run_in(tmp_repo, ["init", "--non-interactive"])
    result = _run_in(tmp_repo, ["build"])
    assert result.exit_code == 0  # type: ignore[attr-defined]
    assert (tmp_repo / ".codegraph" / "graph.db").exists()


def test_status_reports_nodes(tmp_repo: Path) -> None:
    _run_in(tmp_repo, ["init", "--non-interactive"])
    _run_in(tmp_repo, ["build"])
    result = _run_in(tmp_repo, ["status"])
    assert result.exit_code == 0  # type: ignore[attr-defined]
    assert "Nodes" in result.stdout  # type: ignore[attr-defined]
