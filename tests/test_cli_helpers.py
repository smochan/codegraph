"""Tests for codegraph.cli helpers: _get_data_dir and _open_graph."""
from __future__ import annotations

from pathlib import Path

import pytest

from codegraph import cli
from codegraph.graph.builder import GraphBuilder
from codegraph.graph.store_sqlite import SQLiteGraphStore


@pytest.fixture(autouse=True)
def _reset_data_dir_state():
    saved = cli._DATA_DIR_STATE.get("value")
    cli._DATA_DIR_STATE["value"] = None
    yield
    cli._DATA_DIR_STATE["value"] = saved


def test_get_data_dir_returns_state_when_set(tmp_path: Path) -> None:
    override = tmp_path / "override-data"
    cli._DATA_DIR_STATE["value"] = override
    assert cli._get_data_dir(tmp_path) == override


def test_get_data_dir_falls_back_to_default(tmp_path: Path) -> None:
    cli._DATA_DIR_STATE["value"] = None
    out = cli._get_data_dir(tmp_path)
    assert out == tmp_path / ".codegraph"


def test_get_data_dir_state_none_uses_default(tmp_path: Path) -> None:
    # explicit None semantics (key present, value None)
    cli._DATA_DIR_STATE["value"] = None
    assert cli._get_data_dir(tmp_path) == tmp_path / ".codegraph"


def test_open_graph_returns_none_when_db_missing(tmp_path: Path) -> None:
    # No DB built — should print warning and return None.
    cli._DATA_DIR_STATE["value"] = tmp_path / "nope"
    assert cli._open_graph(tmp_path) is None


def test_open_graph_returns_digraph_for_existing_db(tmp_path: Path) -> None:
    # Build a tiny repo, persist its graph, then read via _open_graph.
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "m.py").write_text("def hello():\n    return 1\n", encoding="utf-8")
    data_dir = tmp_path / ".cgdata"
    data_dir.mkdir()
    db_path = data_dir / "graph.db"
    store = SQLiteGraphStore(db_path)
    GraphBuilder(repo, store).build(incremental=False)
    store.close()

    cli._DATA_DIR_STATE["value"] = data_dir
    g = cli._open_graph(repo)
    assert g is not None
    assert g.number_of_nodes() > 0
