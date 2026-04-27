"""DF1: HTTP route extraction + SQLAlchemy READS_FROM / WRITES_TO.

Each test writes a small fixture into a temporary directory, runs
``PythonExtractor`` on it, and asserts the right ROUTE / READS_FROM /
WRITES_TO edges land with the right metadata.

The SQL tests build a tiny multi-file repo via ``GraphBuilder`` so the
post-build resolver can rewrite ``unresolved::Model`` edges to real
CLASS node ids. ROUTE tests skip the resolver since synthetic route
nodes are emitted directly by the parser.
"""
from __future__ import annotations

from pathlib import Path

import networkx as nx
import pytest

from codegraph.graph.builder import GraphBuilder
from codegraph.graph.schema import Edge, EdgeKind, Node
from codegraph.graph.store_networkx import to_digraph
from codegraph.graph.store_sqlite import SQLiteGraphStore
from codegraph.parsers.python import PythonExtractor
from codegraph.viz.hld import build_hld

# --- Helpers -----------------------------------------------------------


def _run_extractor(
    tmp_path: Path, src: str, filename: str = "sample.py"
) -> tuple[list[Node], list[Edge]]:
    target = tmp_path / filename
    target.write_text(src)
    return PythonExtractor().parse_file(target, tmp_path)


def _route_edges(edges: list[Edge]) -> list[Edge]:
    return [e for e in edges if e.kind == EdgeKind.ROUTE]


def _build_repo_graph(tmp_path: Path) -> nx.MultiDiGraph:
    """Run a full GraphBuilder pass over ``tmp_path`` and return the graph."""
    db = tmp_path / ".codegraph" / "graph.db"
    db.parent.mkdir(parents=True, exist_ok=True)
    store = SQLiteGraphStore(db)
    GraphBuilder(tmp_path, store).build(incremental=False)
    graph = to_digraph(store)
    store.close()
    return graph


def _edges_of_kind(graph: nx.MultiDiGraph, kind: str) -> list[tuple[str, str, dict]]:
    return [
        (s, d, dict(data))
        for s, d, data in graph.edges(data=True)
        if str(data.get("kind") or "") == kind
    ]


# --- Part A: ROUTE edges ----------------------------------------------


def test_fastapi_app_get_emits_route_edge(tmp_path: Path) -> None:
    src = (
        "@app.get('/')\n"
        "def index():\n"
        "    return {}\n"
    )
    _, edges = _run_extractor(tmp_path, src)
    routes = _route_edges(edges)
    assert len(routes) == 1
    assert routes[0].metadata == {
        "method": "GET", "path": "/", "framework": "fastapi",
    }


def test_fastapi_apirouter_post_emits_route(tmp_path: Path) -> None:
    src = (
        "@router.post('/items')\n"
        "def create_item(payload: dict):\n"
        "    return payload\n"
    )
    _, edges = _run_extractor(tmp_path, src)
    routes = _route_edges(edges)
    assert len(routes) == 1
    assert routes[0].metadata["method"] == "POST"
    assert routes[0].metadata["path"] == "/items"
    assert routes[0].metadata["framework"] == "fastapi"


def test_fastapi_path_param_preserved(tmp_path: Path) -> None:
    src = (
        "@app.get('/items/{id}')\n"
        "def get_item(id: int):\n"
        "    return id\n"
    )
    _, edges = _run_extractor(tmp_path, src)
    routes = _route_edges(edges)
    assert len(routes) == 1
    assert routes[0].metadata["path"] == "/items/{id}"


def test_flask_app_route_with_methods_emits_one_per_method(
    tmp_path: Path,
) -> None:
    src = (
        "@app.route('/', methods=['POST', 'PUT'])\n"
        "def root():\n"
        "    return ''\n"
    )
    _, edges = _run_extractor(tmp_path, src)
    routes = _route_edges(edges)
    methods = sorted(e.metadata["method"] for e in routes)
    assert methods == ["POST", "PUT"]
    for r in routes:
        assert r.metadata["framework"] == "flask"
        assert r.metadata["path"] == "/"


def test_flask_blueprint_route_default_get(tmp_path: Path) -> None:
    src = (
        "@blueprint.route('/x')\n"
        "def x():\n"
        "    return ''\n"
    )
    _, edges = _run_extractor(tmp_path, src)
    routes = _route_edges(edges)
    assert len(routes) == 1
    assert routes[0].metadata["method"] == "GET"
    assert routes[0].metadata["path"] == "/x"
    assert routes[0].metadata["framework"] == "flask"


def test_decorator_without_path_arg_skips(tmp_path: Path) -> None:
    src = (
        "@app.get\n"
        "def weird():\n"
        "    return ''\n"
    )
    _, edges = _run_extractor(tmp_path, src)
    assert _route_edges(edges) == []


# --- Part B: READS_FROM / WRITES_TO edges -----------------------------


def _write_models_module(tmp_path: Path) -> None:
    """Create a models.py with a User CLASS for the SQL tests."""
    (tmp_path / "models.py").write_text(
        "class User:\n"
        "    pass\n"
    )


def test_session_query_emits_reads_from(tmp_path: Path) -> None:
    _write_models_module(tmp_path)
    (tmp_path / "service.py").write_text(
        "from models import User\n"
        "def list_users(session):\n"
        "    return session.query(User).all()\n"
    )
    graph = _build_repo_graph(tmp_path)
    rows = _edges_of_kind(graph, "READS_FROM")
    assert len(rows) == 1
    _src, _dst, data = rows[0]
    assert data["metadata"]["operation"] == "select"
    assert data["metadata"]["via"] == "session.query"


def test_db_session_query_works(tmp_path: Path) -> None:
    _write_models_module(tmp_path)
    (tmp_path / "service.py").write_text(
        "from models import User\n"
        "def list_users(db):\n"
        "    return db.session.query(User).all()\n"
    )
    graph = _build_repo_graph(tmp_path)
    rows = _edges_of_kind(graph, "READS_FROM")
    assert len(rows) == 1
    assert rows[0][2]["metadata"]["operation"] == "select"


def test_model_query_filter_emits_reads_from(tmp_path: Path) -> None:
    _write_models_module(tmp_path)
    (tmp_path / "service.py").write_text(
        "from models import User\n"
        "def find_user(uid):\n"
        "    return User.query.filter(User.id == uid).first()\n"
    )
    graph = _build_repo_graph(tmp_path)
    rows = _edges_of_kind(graph, "READS_FROM")
    assert len(rows) >= 1
    via_set = {r[2]["metadata"]["via"] for r in rows}
    assert "Model.query" in via_set


def test_session_add_emits_writes_to(tmp_path: Path) -> None:
    _write_models_module(tmp_path)
    (tmp_path / "service.py").write_text(
        "from models import User\n"
        "def create(session, name):\n"
        "    session.add(User(name=name))\n"
    )
    graph = _build_repo_graph(tmp_path)
    rows = _edges_of_kind(graph, "WRITES_TO")
    assert len(rows) == 1
    assert rows[0][2]["metadata"]["operation"] == "insert"
    assert rows[0][2]["metadata"]["via"] == "session.add"


def test_session_execute_update_emits_writes_to(tmp_path: Path) -> None:
    _write_models_module(tmp_path)
    (tmp_path / "service.py").write_text(
        "from models import User\n"
        "from sqlalchemy import update\n"
        "def bump(session):\n"
        "    session.execute(update(User).values(name='x'))\n"
    )
    graph = _build_repo_graph(tmp_path)
    rows = _edges_of_kind(graph, "WRITES_TO")
    assert len(rows) == 1
    assert rows[0][2]["metadata"]["operation"] == "update"


def test_session_execute_delete_emits_writes_to(tmp_path: Path) -> None:
    _write_models_module(tmp_path)
    (tmp_path / "service.py").write_text(
        "from models import User\n"
        "from sqlalchemy import delete\n"
        "def purge(session):\n"
        "    session.execute(delete(User))\n"
    )
    graph = _build_repo_graph(tmp_path)
    rows = _edges_of_kind(graph, "WRITES_TO")
    assert len(rows) == 1
    assert rows[0][2]["metadata"]["operation"] == "delete"


def test_unresolved_model_name_does_not_emit_edge(tmp_path: Path) -> None:
    # No models.py defining ``Ghost`` — the unresolved edge must be dropped.
    (tmp_path / "service.py").write_text(
        "def bad(session):\n"
        "    return session.query(Ghost).all()\n"
    )
    graph = _build_repo_graph(tmp_path)
    rows = _edges_of_kind(graph, "READS_FROM")
    assert rows == []


# --- Part C: HLD payload integration ----------------------------------


def test_hld_payload_routes_and_sql_io_populated(tmp_path: Path) -> None:
    _write_models_module(tmp_path)
    (tmp_path / "api.py").write_text(
        "from models import User\n"
        "@app.get('/users')\n"
        "def list_users(session):\n"
        "    return session.query(User).all()\n"
        "\n"
        "@app.post('/users')\n"
        "def create(session, name):\n"
        "    session.add(User(name=name))\n"
    )
    graph = _build_repo_graph(tmp_path)
    payload = build_hld(graph)

    # routes — one per (method, path).
    paths = sorted(r["path"] + ":" + r["method"] for r in payload.routes)
    assert paths == ["/users:GET", "/users:POST"]
    for r in payload.routes:
        assert r["framework"] == "fastapi"
        assert r["handler_qn"]  # non-empty

    # sql_io — both a READS_FROM and a WRITES_TO.
    kinds = sorted(r["kind"] for r in payload.sql_io)
    assert kinds == ["READS_FROM", "WRITES_TO"]
    for r in payload.sql_io:
        assert r["model_qn"].endswith(".User") or r["model_qn"] == "User"
        assert r["function_qn"]


# --- Bonus: synthetic route node carries the right metadata ----------


def test_route_synthetic_node_has_synthetic_kind_metadata(
    tmp_path: Path,
) -> None:
    src = (
        "@app.get('/health')\n"
        "def health():\n"
        "    return 'ok'\n"
    )
    nodes, edges = _run_extractor(tmp_path, src)
    route_edge = _route_edges(edges)[0]
    synth = next(n for n in nodes if n.id == route_edge.dst)
    assert synth.metadata["synthetic_kind"] == "ROUTE"
    assert synth.metadata["method"] == "GET"
    assert synth.metadata["path"] == "/health"


@pytest.mark.parametrize(
    "verb,upper",
    [
        ("get", "GET"), ("post", "POST"), ("put", "PUT"),
        ("delete", "DELETE"), ("patch", "PATCH"),
    ],
)
def test_fastapi_all_verbs(tmp_path: Path, verb: str, upper: str) -> None:
    src = (
        f"@app.{verb}('/x')\n"
        "def h():\n"
        "    return 1\n"
    )
    _, edges = _run_extractor(tmp_path, src)
    routes = _route_edges(edges)
    assert len(routes) == 1
    assert routes[0].metadata["method"] == upper
