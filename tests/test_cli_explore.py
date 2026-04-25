"""CLI smoke tests for the ``codegraph explore`` command."""
from __future__ import annotations

import shutil
from pathlib import Path

from typer.testing import CliRunner

from codegraph.cli import app
from codegraph.graph.builder import GraphBuilder
from codegraph.graph.store_sqlite import SQLiteGraphStore

FIXTURES = Path(__file__).parent / "fixtures"
runner = CliRunner()


def _setup_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    shutil.copytree(FIXTURES / "python_sample", repo / "pkg")
    data_dir = repo / ".codegraph"
    data_dir.mkdir()
    store = SQLiteGraphStore(data_dir / "graph.db")
    GraphBuilder(repo, store).build(incremental=False)
    store.close()
    return repo


def test_explore_command_writes_dashboard(tmp_path: Path) -> None:
    repo = _setup_repo(tmp_path)
    import os

    cwd = os.getcwd()
    try:
        os.chdir(repo)
        out_dir = repo / "out"
        result = runner.invoke(
            app,
            [
                "explore",
                "--output",
                str(out_dir),
                "--top-files",
                "3",
                "--callgraph-limit",
                "100",
            ],
        )
    finally:
        os.chdir(cwd)

    assert result.exit_code == 0, result.output
    assert "dashboard written" in result.output
    assert (out_dir / "index.html").exists()
    assert (out_dir / "architecture.html").exists()
    assert (out_dir / "callgraph.html").exists()
    assert (out_dir / "inheritance.html").exists()


def test_explore_without_graph_exits_nonzero(tmp_path: Path) -> None:
    import os

    repo = tmp_path / "empty"
    repo.mkdir()
    cwd = os.getcwd()
    try:
        os.chdir(repo)
        result = runner.invoke(app, ["explore", "--output", str(repo / "out")])
    finally:
        os.chdir(cwd)
    assert result.exit_code != 0
    assert "No graph found" in result.output
