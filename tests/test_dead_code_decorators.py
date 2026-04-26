"""Tests that decorator-aware dead-code analysis spares framework entry points."""
from __future__ import annotations

import shutil
from pathlib import Path

import networkx as nx
import pytest

from codegraph.analysis import find_dead_code
from codegraph.config import CodegraphConfig, DeadCodeConfig
from codegraph.graph.builder import GraphBuilder
from codegraph.graph.store_networkx import to_digraph
from codegraph.graph.store_sqlite import SQLiteGraphStore

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def decorator_graph(tmp_path: Path) -> nx.MultiDiGraph:
    repo = tmp_path / "repo"
    repo.mkdir()
    shutil.copytree(FIXTURES / "decorators_sample", repo / "pkg")
    store = SQLiteGraphStore(tmp_path / "graph.db")
    GraphBuilder(repo, store).build(incremental=False)
    g = to_digraph(store)
    store.close()
    return g


def _dead_qualnames(graph: nx.MultiDiGraph) -> set[str]:
    return {d.qualname for d in find_dead_code(graph)}


def _entry_point_qualnames(graph: nx.MultiDiGraph) -> set[str]:
    out: set[str] = set()
    for _, attrs in graph.nodes(data=True):
        meta = attrs.get("metadata") or {}
        if meta.get("entry_point"):
            qn = attrs.get("qualname")
            if qn:
                out.add(str(qn))
    return out


def test_typer_commands_not_flagged_dead(decorator_graph: nx.MultiDiGraph) -> None:
    dead = _dead_qualnames(decorator_graph)
    assert not any(q.endswith(".greet") for q in dead)
    assert not any(q.endswith(".farewell") for q in dead)
    assert not any(q.endswith(".main_callback") for q in dead)


def test_fastapi_routes_not_flagged_dead(decorator_graph: nx.MultiDiGraph) -> None:
    dead = _dead_qualnames(decorator_graph)
    assert not any(q.endswith(".health_check") for q in dead)
    assert not any(q.endswith(".create_item") for q in dead)


def test_pytest_fixtures_not_flagged_dead(decorator_graph: nx.MultiDiGraph) -> None:
    dead = _dead_qualnames(decorator_graph)
    assert not any(q.endswith(".db_connection") for q in dead)
    assert not any(q.endswith(".app_client") for q in dead)
    assert not any(q.endswith(".regression_check") for q in dead)


def test_abstract_methods_not_flagged_dead(decorator_graph: nx.MultiDiGraph) -> None:
    dead = _dead_qualnames(decorator_graph)
    assert not any(q.endswith(".find_by_id") for q in dead)
    assert not any(q.endswith(".save") for q in dead)


def test_celery_tasks_not_flagged_dead(decorator_graph: nx.MultiDiGraph) -> None:
    dead = _dead_qualnames(decorator_graph)
    assert not any(q.endswith(".process_payment") for q in dead)
    assert not any(q.endswith(".cleanup_files") for q in dead)


def test_internal_helpers_still_flagged_dead(
    decorator_graph: nx.MultiDiGraph,
) -> None:
    dead = _dead_qualnames(decorator_graph)
    assert any(q.endswith("._internal_helper") for q in dead)
    assert any(q.endswith("._validate_item") for q in dead)
    assert any(q.endswith("._setup_db") for q in dead)
    assert any(q.endswith("._local_helper") for q in dead)


def test_entry_point_metadata_set_on_decorated_nodes(
    decorator_graph: nx.MultiDiGraph,
) -> None:
    eps = _entry_point_qualnames(decorator_graph)
    assert any(q.endswith(".greet") for q in eps)
    assert any(q.endswith(".health_check") for q in eps)
    assert any(q.endswith(".db_connection") for q in eps)
    assert any(q.endswith(".find_by_id") for q in eps)
    assert any(q.endswith(".process_payment") for q in eps)
    # Helpers must NOT be flagged as entry points.
    assert not any(q.endswith("._internal_helper") for q in eps)


def test_dead_code_skip_with_entry_point_flag() -> None:
    """Synthetic graph: a node with entry_point metadata is never dead."""
    g: nx.MultiDiGraph = nx.MultiDiGraph()
    g.add_node(
        "fn::demo",
        kind="FUNCTION",
        name="demo",
        qualname="pkg.demo",
        file="pkg/demo.py",
        line_start=1,
        metadata={"entry_point": True, "decorators": ["@app.command()"]},
    )
    dead = find_dead_code(g)
    assert all(d.id != "fn::demo" for d in dead)


def test_user_supplied_decorator_pattern_honored(tmp_path: Path) -> None:
    """User-supplied custom decorator pattern in DeadCodeConfig is honored."""
    repo = tmp_path / "repo"
    repo.mkdir()
    pkg = repo / "pkg"
    pkg.mkdir()
    (pkg / "custom.py").write_text(
        "def _make_app():\n"
        "    return object()\n\n"
        "my_handler = _make_app()\n\n"
        "@my_handler.register\n"
        "def custom_entry() -> None:\n"
        "    pass\n"
    )
    cfg = CodegraphConfig(
        dead_code=DeadCodeConfig(
            entry_point_decorators=["@my_handler.register"]
        )
    )
    store = SQLiteGraphStore(tmp_path / "graph.db")
    GraphBuilder(repo, store, config=cfg).build(incremental=False)
    g = to_digraph(store)
    store.close()
    dead = {d.qualname for d in find_dead_code(g)}
    assert not any(q.endswith(".custom_entry") for q in dead)
