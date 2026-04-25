"""Tests for GraphBuilder."""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from codegraph.graph.builder import GraphBuilder
from codegraph.graph.store_sqlite import SQLiteGraphStore

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def fixture_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    shutil.copytree(FIXTURES / "python_sample", repo / "python_sample")
    shutil.copytree(FIXTURES / "ts_sample", repo / "ts_sample")
    return repo


@pytest.fixture
def store(tmp_path: Path) -> SQLiteGraphStore:
    return SQLiteGraphStore(tmp_path / "graph.db")


def test_build_nonzero_nodes_edges(
    fixture_repo: Path, store: SQLiteGraphStore
) -> None:
    builder = GraphBuilder(fixture_repo, store)
    stats = builder.build(incremental=False)
    assert stats.files_scanned > 0
    assert stats.nodes_added > 0
    assert store.count_nodes() > 0


def test_build_incremental_noop(
    fixture_repo: Path, store: SQLiteGraphStore
) -> None:
    builder = GraphBuilder(fixture_repo, store)
    stats1 = builder.build(incremental=False)
    stats2 = builder.build(incremental=True)
    assert stats2.files_skipped == stats1.files_scanned
    assert stats2.nodes_added == 0


def test_build_errors_dont_crash(
    fixture_repo: Path, store: SQLiteGraphStore
) -> None:
    bad = fixture_repo / "python_sample" / "broken.py"
    bad.write_bytes(b"\xff\xfe invalid bytes \x00\x01")
    builder = GraphBuilder(fixture_repo, store)
    stats = builder.build(incremental=False)
    assert stats.files_scanned > 0
