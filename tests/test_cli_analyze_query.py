"""CLI tests for analyze + query subcommands."""
from __future__ import annotations

import json
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


def test_analyze_markdown(built_repo: Path) -> None:
    result = _run(built_repo, ["analyze"])
    assert result.exit_code == 0  # type: ignore[attr-defined]
    assert "codegraph analysis" in result.stdout  # type: ignore[attr-defined]


def test_analyze_json(built_repo: Path) -> None:
    result = _run(built_repo, ["analyze", "--format", "json"])
    assert result.exit_code == 0  # type: ignore[attr-defined]
    data = json.loads(result.stdout)  # type: ignore[attr-defined]
    assert "metrics" in data
    assert "dead_code" in data
    assert "untested" in data


def test_analyze_writes_output_file(
    built_repo: Path, tmp_path: Path
) -> None:
    out = built_repo / "report.md"
    result = _run(built_repo, ["analyze", "--output", str(out)])
    assert result.exit_code == 0  # type: ignore[attr-defined]
    assert out.exists()
    assert "codegraph analysis" in out.read_text()


def test_query_callers(built_repo: Path) -> None:
    result = _run(built_repo, ["query", "callers", "count_words"])
    assert result.exit_code == 0  # type: ignore[attr-defined]
    assert "Callers of" in result.stdout  # type: ignore[attr-defined]


def test_query_untested(built_repo: Path) -> None:
    result = _run(built_repo, ["query", "untested"])
    assert result.exit_code == 0  # type: ignore[attr-defined]
    assert "untested" in result.stdout.lower()  # type: ignore[attr-defined]


def test_query_deadcode(built_repo: Path) -> None:
    result = _run(built_repo, ["query", "deadcode"])
    assert result.exit_code == 0  # type: ignore[attr-defined]
    assert "dead-code" in result.stdout.lower()  # type: ignore[attr-defined]


def test_query_cycles(built_repo: Path) -> None:
    result = _run(built_repo, ["query", "cycles"])
    assert result.exit_code == 0  # type: ignore[attr-defined]
    assert "Cycles" in result.stdout  # type: ignore[attr-defined]


def test_query_subgraph(built_repo: Path) -> None:
    result = _run(built_repo, ["query", "subgraph", "Dog", "--depth", "1"])
    assert result.exit_code == 0  # type: ignore[attr-defined]
    assert "flowchart" in result.stdout  # type: ignore[attr-defined]


def test_query_unknown_symbol_exits_nonzero(built_repo: Path) -> None:
    result = _run(built_repo, ["query", "callers", "definitely_not_here_xyz"])
    assert result.exit_code != 0  # type: ignore[attr-defined]


def test_analyze_without_graph_exits_nonzero(tmp_path: Path) -> None:
    repo = tmp_path / "empty"
    repo.mkdir()
    result = _run(repo, ["analyze"])
    assert result.exit_code != 0  # type: ignore[attr-defined]
