"""Tests for the architectural role classifier (DF1.5)."""
from __future__ import annotations

import shutil
from pathlib import Path

import networkx as nx
import pytest

from codegraph.analysis.roles import classify_roles
from codegraph.graph.builder import GraphBuilder
from codegraph.graph.schema import EdgeKind, NodeKind
from codegraph.graph.store_networkx import to_digraph
from codegraph.graph.store_sqlite import SQLiteGraphStore

FIXTURES = Path(__file__).parent / "fixtures" / "roles"


def _build_graph(tmp_path: Path, *files: str) -> nx.MultiDiGraph:
    repo = tmp_path / "repo"
    pkg = repo / "pkg"
    pkg.mkdir(parents=True)
    for fname in files:
        shutil.copy(FIXTURES / fname, pkg / fname)
    store = SQLiteGraphStore(tmp_path / "graph.db")
    GraphBuilder(repo, store).build(incremental=False)
    g = to_digraph(store)
    store.close()
    return g


def _role_for(graph: nx.MultiDiGraph, qualname_suffix: str) -> str | None:
    for _, attrs in graph.nodes(data=True):
        qn = str(attrs.get("qualname") or "")
        if qn.endswith(qualname_suffix):
            meta = attrs.get("metadata") or {}
            role = meta.get("role")
            return None if role is None else str(role)
    raise AssertionError(f"node ending in {qualname_suffix!r} not found")


def test_fastapi_decorated_function_is_handler(tmp_path: Path) -> None:
    g = _build_graph(tmp_path, "fastapi_app.py")
    assert _role_for(g, ".health_check") == "HANDLER"
    assert _role_for(g, ".create_item") == "HANDLER"


def test_flask_route_is_handler(tmp_path: Path) -> None:
    g = _build_graph(tmp_path, "flask_app.py")
    assert _role_for(g, ".index") == "HANDLER"


def test_user_service_class_and_methods_are_service(tmp_path: Path) -> None:
    g = _build_graph(tmp_path, "services.py")
    assert _role_for(g, ".UserService") == "SERVICE"
    assert _role_for(g, "UserService.get_user") == "SERVICE"
    assert _role_for(g, "UserService.delete_user") == "SERVICE"


def test_injectable_class_is_service(tmp_path: Path) -> None:
    g = _build_graph(tmp_path, "services.py")
    assert _role_for(g, ".PaymentProcessor") == "SERVICE"
    assert _role_for(g, "PaymentProcessor.charge") == "SERVICE"


def test_repository_class_and_methods_are_repo(tmp_path: Path) -> None:
    g = _build_graph(tmp_path, "repositories.py")
    assert _role_for(g, ".OrderRepository") == "REPO"
    assert _role_for(g, "OrderRepository.find_by_id") == "REPO"
    assert _role_for(g, "OrderRepository.save") == "REPO"


def test_pascal_case_function_in_tsx_is_component(tmp_path: Path) -> None:
    g = _build_graph(tmp_path, "Component.tsx")
    assert _role_for(g, ".UserCard") == "COMPONENT"


def test_react_component_class_is_component() -> None:
    """Synthetic graph: a TS class with INHERITS edge to React.Component."""
    g: nx.MultiDiGraph = nx.MultiDiGraph()
    g.add_node(
        "cls::Legacy",
        kind=NodeKind.CLASS.value,
        name="Legacy",
        qualname="pkg.Legacy",
        file="pkg/Legacy.tsx",
        line_start=1,
        language="typescript",
        metadata={},
    )
    g.add_node(
        "unresolved::React.Component",
        kind="UNRESOLVED",
        name="React.Component",
        qualname="React.Component",
        file="",
        line_start=0,
        language="typescript",
        metadata={},
    )
    g.add_edge(
        "cls::Legacy",
        "unresolved::React.Component",
        key=EdgeKind.INHERITS.value,
        kind=EdgeKind.INHERITS.value,
        metadata={"target_name": "React.Component"},
    )
    classify_roles(g)
    assert g.nodes["cls::Legacy"]["metadata"]["role"] == "COMPONENT"


def test_handler_priority_over_service_on_method(tmp_path: Path) -> None:
    """A SERVICE class with an HTTP-decorated method: method stays HANDLER."""
    g = _build_graph(tmp_path, "mixed_handler_service.py")
    assert _role_for(g, ".ReportService") == "SERVICE"
    assert _role_for(g, "ReportService.list_reports") == "HANDLER"
    # Non-handler method on the SERVICE class still gets SERVICE.
    assert _role_for(g, "ReportService.build_report") == "SERVICE"


def test_plain_class_has_no_role(tmp_path: Path) -> None:
    g = _build_graph(tmp_path, "services.py")
    assert _role_for(g, ".User") is None


def test_classify_roles_returns_count_matching_annotated_nodes() -> None:
    """Counter return value matches number of nodes annotated."""
    g: nx.MultiDiGraph = nx.MultiDiGraph()
    g.add_node(
        "cls::Svc",
        kind=NodeKind.CLASS.value,
        name="OrderService",
        qualname="pkg.OrderService",
        file="pkg/svc.py",
        line_start=1,
        language="python",
        metadata={},
    )
    g.add_node(
        "m::process",
        kind=NodeKind.METHOD.value,
        name="process",
        qualname="pkg.OrderService.process",
        file="pkg/svc.py",
        line_start=2,
        language="python",
        metadata={},
    )
    g.add_edge(
        "m::process",
        "cls::Svc",
        key=EdgeKind.DEFINED_IN.value,
        kind=EdgeKind.DEFINED_IN.value,
        metadata={},
    )
    g.add_node(
        "fn::plain",
        kind=NodeKind.FUNCTION.value,
        name="plain",
        qualname="pkg.plain",
        file="pkg/util.py",
        line_start=1,
        language="python",
        metadata={},
    )

    count = classify_roles(g)
    annotated = sum(
        1
        for _, attrs in g.nodes(data=True)
        if (attrs.get("metadata") or {}).get("role")
    )
    assert count == annotated
    assert count == 2  # OrderService class + .process method
    assert g.nodes["fn::plain"]["metadata"].get("role") in (None, )


def test_classify_roles_idempotent() -> None:
    """Running the classifier twice should not change results."""
    g: nx.MultiDiGraph = nx.MultiDiGraph()
    g.add_node(
        "cls::Repo",
        kind=NodeKind.CLASS.value,
        name="UserRepository",
        qualname="pkg.UserRepository",
        file="pkg/repo.py",
        line_start=1,
        language="python",
        metadata={},
    )
    first = classify_roles(g)
    second = classify_roles(g)
    assert first == 1
    # Second run does not change roles (priority logic short-circuits).
    assert second == 0 or second == 1
    assert g.nodes["cls::Repo"]["metadata"]["role"] == "REPO"


def test_handler_decorator_substring_route(tmp_path: Path) -> None:
    """Decorators containing 'route' substring are treated as handlers."""
    g: nx.MultiDiGraph = nx.MultiDiGraph()
    g.add_node(
        "fn::endpoint",
        kind=NodeKind.FUNCTION.value,
        name="my_endpoint",
        qualname="pkg.my_endpoint",
        file="pkg/api.py",
        line_start=1,
        language="python",
        metadata={"decorators": ["@some_router.route('/foo')"]},
    )
    classify_roles(g)
    assert g.nodes["fn::endpoint"]["metadata"]["role"] == "HANDLER"


@pytest.mark.parametrize(
    "decorator,expected_role",
    [
        ("@app.get('/x')", "HANDLER"),
        ("@app.post('/x')", "HANDLER"),
        ("@app.delete('/x')", "HANDLER"),
        ("@app.websocket('/ws')", "HANDLER"),
        ("@router.patch('/x')", "HANDLER"),
    ],
)
def test_http_verb_decorators_set_handler(
    decorator: str, expected_role: str
) -> None:
    g: nx.MultiDiGraph = nx.MultiDiGraph()
    g.add_node(
        "fn::h",
        kind=NodeKind.FUNCTION.value,
        name="h",
        qualname="pkg.h",
        file="pkg/api.py",
        line_start=1,
        language="python",
        metadata={"decorators": [decorator]},
    )
    classify_roles(g)
    assert g.nodes["fn::h"]["metadata"]["role"] == expected_role
