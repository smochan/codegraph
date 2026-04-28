"""Tests for codegraph.review.differ."""
from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

import networkx as nx
import pytest

from codegraph.graph.builder import GraphBuilder
from codegraph.graph.store_networkx import to_digraph
from codegraph.graph.store_sqlite import SQLiteGraphStore
from codegraph.review.differ import diff_graphs

FIXTURES = Path(__file__).parent / "fixtures"


def _build_graph(repo: Path, db_path: Path) -> nx.MultiDiGraph:
    store = SQLiteGraphStore(db_path)
    GraphBuilder(repo, store).build(incremental=False)
    g = to_digraph(store)
    store.close()
    return g


@pytest.fixture
def graphs(tmp_path: Path) -> tuple[nx.MultiDiGraph, nx.MultiDiGraph]:
    old_repo = tmp_path / "old"
    new_repo = tmp_path / "new"
    old_repo.mkdir()
    new_repo.mkdir()
    shutil.copytree(FIXTURES / "python_sample", old_repo / "pkg")
    shutil.copytree(FIXTURES / "python_sample_v2", new_repo / "pkg")
    old_g = _build_graph(old_repo, tmp_path / "old.db")
    new_g = _build_graph(new_repo, tmp_path / "new.db")
    return old_g, new_g


def _qualnames(items: list[Any]) -> set[str]:
    return {i.qualname for i in items}


def test_diff_detects_added_node(
    graphs: tuple[nx.MultiDiGraph, nx.MultiDiGraph],
) -> None:
    old_g, new_g = graphs
    diff = diff_graphs(old_g, new_g)
    added = _qualnames(diff.added_nodes)
    assert any("new_function" in q for q in added)


def test_diff_detects_removed_node(
    graphs: tuple[nx.MultiDiGraph, nx.MultiDiGraph],
) -> None:
    old_g, new_g = graphs
    diff = diff_graphs(old_g, new_g)
    removed = _qualnames(diff.removed_nodes)
    assert any(q.endswith("Dog.fetch") for q in removed)


def test_diff_detects_modified_signature(
    graphs: tuple[nx.MultiDiGraph, nx.MultiDiGraph],
) -> None:
    old_g, new_g = graphs
    diff = diff_graphs(old_g, new_g)
    modified = [m for m in diff.modified_nodes if m.qualname.endswith("Dog.speak")]
    assert modified, "expected Dog.speak to be reported as modified"
    details = modified[0].details
    assert "signature" in details
    assert details["signature"]["old"] != details["signature"]["new"]


def test_diff_identical_graphs_have_no_changes(tmp_path: Path) -> None:
    repo = tmp_path / "r"
    repo.mkdir()
    shutil.copytree(FIXTURES / "python_sample", repo / "pkg")
    g1 = _build_graph(repo, tmp_path / "a.db")
    g2 = _build_graph(repo, tmp_path / "b.db")
    diff = diff_graphs(g1, g2)
    assert not diff.added_nodes
    assert not diff.removed_nodes
    assert not diff.modified_nodes
    assert not diff.added_edges
    assert not diff.removed_edges


def test_diff_total_property() -> None:
    g1: nx.MultiDiGraph = nx.MultiDiGraph()
    g2: nx.MultiDiGraph = nx.MultiDiGraph()
    g2.add_node(
        "n1",
        qualname="pkg.foo",
        kind="FUNCTION",
        file="pkg/foo.py",
        line_start=1,
        signature="foo()",
    )
    diff = diff_graphs(g1, g2)
    assert diff.total == 1


def _add_func(
    g: nx.MultiDiGraph,
    qn: str,
    *,
    file: str = "pkg/foo.py",
    line: int = 1,
    signature: str | None = None,
) -> None:
    nid = f"node::{qn}"
    g.add_node(
        nid,
        qualname=qn,
        kind="FUNCTION",
        file=file,
        line_start=line,
        signature=signature if signature is not None else f"{qn.split('.')[-1]}()",
    )


def test_pure_line_shift_is_NOT_modified() -> None:
    """Regression test: a function whose only change is a line-number shift
    (because the PR added lines elsewhere in the file) MUST NOT be flagged
    as modified.

    Before the fix this produced a false-positive ``modified-signature``
    finding on every function in the file, blocking PR #15 with 50 noise
    findings on a clean change.
    """
    old_g: nx.MultiDiGraph = nx.MultiDiGraph()
    new_g: nx.MultiDiGraph = nx.MultiDiGraph()
    # Same function, same file, same signature — only line moved 1 -> 8.
    _add_func(old_g, "pkg.app.esc", file="app.js", line=1, signature="esc(s)")
    _add_func(new_g, "pkg.app.esc", file="app.js", line=8, signature="esc(s)")
    diff = diff_graphs(old_g, new_g)
    assert diff.modified_nodes == [], (
        f"line-only shift should NOT trigger modified, got: {diff.modified_nodes}"
    )


def test_real_signature_change_IS_modified() -> None:
    """Real signature change (params changed) IS still flagged as modified."""
    old_g: nx.MultiDiGraph = nx.MultiDiGraph()
    new_g: nx.MultiDiGraph = nx.MultiDiGraph()
    _add_func(old_g, "pkg.foo", line=1, signature="foo(x)")
    _add_func(new_g, "pkg.foo", line=1, signature="foo(x, y)")
    diff = diff_graphs(old_g, new_g)
    assert len(diff.modified_nodes) == 1
    assert diff.modified_nodes[0].qualname == "pkg.foo"


def test_file_move_IS_modified() -> None:
    """Moving a function to a different file IS still flagged as modified
    (might be a real refactor that callers haven't been updated for)."""
    old_g: nx.MultiDiGraph = nx.MultiDiGraph()
    new_g: nx.MultiDiGraph = nx.MultiDiGraph()
    _add_func(old_g, "pkg.foo", file="pkg/old.py", signature="foo()")
    _add_func(new_g, "pkg.foo", file="pkg/new.py", signature="foo()")
    diff = diff_graphs(old_g, new_g)
    assert len(diff.modified_nodes) == 1


def test_line_shift_AND_signature_change_records_both_in_details() -> None:
    """When a real signature change AND a line shift happen together,
    both deltas are recorded in details for the rule to inspect — but
    line_start alone never triggers the modified state."""
    old_g: nx.MultiDiGraph = nx.MultiDiGraph()
    new_g: nx.MultiDiGraph = nx.MultiDiGraph()
    _add_func(old_g, "pkg.foo", line=1, signature="foo(x)")
    _add_func(new_g, "pkg.foo", line=10, signature="foo(x, y)")
    diff = diff_graphs(old_g, new_g)
    assert len(diff.modified_nodes) == 1
    details = diff.modified_nodes[0].details or {}
    assert "signature" in details
    assert "line_start" in details
