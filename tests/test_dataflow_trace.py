"""DF4 — trace builder + CLI + MCP tool."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import networkx as nx
from typer.testing import CliRunner

from codegraph.analysis.dataflow import DataFlow, trace
from codegraph.cli import app
from codegraph.graph.schema import EdgeKind, NodeKind


def _add_func(
    g: nx.MultiDiGraph,
    qn: str,
    *,
    file: str = "app.py",
    line: int = 1,
    role: str | None = None,
    kind: str = NodeKind.FUNCTION.value,
) -> str:
    nid = f"node::{qn}"
    metadata: dict[str, Any] = {}
    if role is not None:
        metadata["role"] = role
    g.add_node(
        nid,
        qualname=qn,
        name=qn.rsplit(".", 1)[-1],
        kind=kind,
        file=file,
        line_start=line,
        metadata=metadata,
    )
    return nid


def _add_calls(
    g: nx.MultiDiGraph,
    src_qn: str,
    dst_qn: str,
    *,
    args: list[str] | None = None,
    kwargs: dict[str, str] | None = None,
) -> None:
    src = f"node::{src_qn}"
    dst = f"node::{dst_qn}"
    g.add_edge(
        src,
        dst,
        key=EdgeKind.CALLS.value,
        kind=EdgeKind.CALLS.value,
        metadata={"args": args or [], "kwargs": kwargs or {}},
    )


# ---- Test 1: simple chain ----
def test_trace_simple_chain() -> None:
    g: nx.MultiDiGraph = nx.MultiDiGraph()
    _add_func(g, "app.a")
    _add_func(g, "app.b")
    _add_func(g, "app.c")
    _add_calls(g, "app.a", "app.b", args=["x"])
    _add_calls(g, "app.b", "app.c", args=["y"])
    flow = trace(g, "app.a")
    assert flow is not None
    assert [h.qualname for h in flow.hops] == ["app.a", "app.b", "app.c"]
    # The args on the second hop come from the call into it
    assert flow.hops[1].args == ["x"]
    assert flow.hops[2].args == ["y"]


# ---- Test 2: non-existent entry ----
def test_trace_missing_entry_returns_none() -> None:
    g: nx.MultiDiGraph = nx.MultiDiGraph()
    _add_func(g, "app.a")
    flow = trace(g, "does.not.exist")
    assert flow is None


# ---- Test 3: max_depth ----
def test_trace_respects_max_depth() -> None:
    g: nx.MultiDiGraph = nx.MultiDiGraph()
    for i in range(10):
        _add_func(g, f"app.f{i}")
    for i in range(9):
        _add_calls(g, f"app.f{i}", f"app.f{i + 1}")
    flow = trace(g, "app.f0", max_depth=3)
    assert flow is not None
    # Entry hop + 3 hops = 4 total
    assert len(flow.hops) == 4


# ---- Test 4: cycle in call graph doesn't loop ----
def test_trace_cycle_safe() -> None:
    g: nx.MultiDiGraph = nx.MultiDiGraph()
    _add_func(g, "app.a")
    _add_func(g, "app.b")
    _add_calls(g, "app.a", "app.b")
    _add_calls(g, "app.b", "app.a")  # cycle
    flow = trace(g, "app.a", max_depth=10)
    assert flow is not None
    assert len(flow.hops) == 2  # a, b — back-edge to a is dropped


# ---- Test 5: layer assignment by .tsx file ----
def test_layer_frontend_via_tsx() -> None:
    g: nx.MultiDiGraph = nx.MultiDiGraph()
    _add_func(g, "ui.UserCard", file="src/UserCard.tsx")
    flow = trace(g, "ui.UserCard")
    assert flow is not None
    assert flow.hops[0].layer == "frontend"


# ---- Test 6: layer assignment by REPO role ----
def test_layer_db_via_role() -> None:
    g: nx.MultiDiGraph = nx.MultiDiGraph()
    _add_func(g, "repo.User", role="REPO", kind=NodeKind.CLASS.value)
    flow = trace(g, "repo.User")
    assert flow is not None
    assert flow.hops[0].layer == "db"


# ---- Test 7: role propagates into the hop ----
def test_role_propagates() -> None:
    g: nx.MultiDiGraph = nx.MultiDiGraph()
    _add_func(g, "svc.UserService.get", role="SERVICE")
    flow = trace(g, "svc.UserService.get")
    assert flow is not None
    assert flow.hops[0].role == "SERVICE"


# ---- Test 8: cross-layer fetch transition ----
def test_fetch_to_route_transition() -> None:
    g: nx.MultiDiGraph = nx.MultiDiGraph()
    # Frontend component
    _add_func(g, "ui.UserCard", file="src/UserCard.tsx", role="COMPONENT")
    # Backend handler
    _add_func(g, "api.get_user", role="HANDLER")
    # ROUTE edge
    g.add_node(
        "route::GET::/api/users/{id}",
        qualname="route::GET::/api/users/{id}",
        kind=NodeKind.VARIABLE.value,
        metadata={"synthetic_kind": "ROUTE"},
    )
    g.add_edge(
        "node::api.get_user",
        "route::GET::/api/users/{id}",
        key=EdgeKind.ROUTE.value,
        kind=EdgeKind.ROUTE.value,
        metadata={"method": "GET", "path": "/api/users/{id}"},
    )
    # FETCH_CALL edge from UserCard
    g.add_node(
        "fetch::GET::/api/users/{id}",
        qualname="fetch::GET::/api/users/{id}",
        kind=NodeKind.VARIABLE.value,
    )
    g.add_edge(
        "node::ui.UserCard",
        "fetch::GET::/api/users/{id}",
        key=EdgeKind.FETCH_CALL.value,
        kind=EdgeKind.FETCH_CALL.value,
        metadata={"method": "GET", "url": "/api/users/{id}", "body_keys": []},
    )
    flow = trace(g, "ui.UserCard")
    assert flow is not None
    qns = [h.qualname for h in flow.hops]
    assert "ui.UserCard" in qns
    assert "api.get_user" in qns
    # Frontend → backend layer transition is observed
    layers = [h.layer for h in flow.hops]
    assert "frontend" in layers
    assert "backend" in layers


# ---- Test 9: db hops via READS_FROM ----
def test_db_hop_via_reads_from() -> None:
    g: nx.MultiDiGraph = nx.MultiDiGraph()
    _add_func(g, "repo.UserRepository.get", role="REPO")
    _add_func(g, "models.User", kind=NodeKind.CLASS.value)
    g.add_edge(
        "node::repo.UserRepository.get",
        "node::models.User",
        key=EdgeKind.READS_FROM.value,
        kind=EdgeKind.READS_FROM.value,
        metadata={"operation": "select"},
    )
    flow = trace(g, "repo.UserRepository.get")
    assert flow is not None
    db_hops = [h for h in flow.hops if h.layer == "db"]
    assert len(db_hops) >= 1
    assert any("User" in h.qualname for h in db_hops)


# ---- Test 10: confidence is min across hops ----
def test_confidence_minimum() -> None:
    g: nx.MultiDiGraph = nx.MultiDiGraph()
    _add_func(g, "ui.Card", file="src/Card.tsx", role="COMPONENT")
    _add_func(g, "api.handler", role="HANDLER")
    g.add_node(
        "route::GET::/api/x/{id}",
        qualname="route::GET::/api/x/{id}",
        kind=NodeKind.VARIABLE.value,
    )
    g.add_edge(
        "node::api.handler",
        "route::GET::/api/x/{id}",
        key=EdgeKind.ROUTE.value,
        kind=EdgeKind.ROUTE.value,
        metadata={"method": "GET", "path": "/api/x/{id}"},
    )
    g.add_node(
        "fetch::GET::/api/x/{id}",
        qualname="fetch::GET::/api/x/{id}",
        kind=NodeKind.VARIABLE.value,
    )
    g.add_edge(
        "node::ui.Card",
        "fetch::GET::/api/x/{id}",
        key=EdgeKind.FETCH_CALL.value,
        kind=EdgeKind.FETCH_CALL.value,
        metadata={"method": "GET", "url": "/api/x/42", "body_keys": []},
    )
    flow = trace(g, "ui.Card")
    assert flow is not None
    # match_route would return 0.9 for placeholder match
    assert flow.confidence < 1.0


# ---- Test 11: CLI dataflow trace works ----
def test_cli_dataflow_trace_smoke(tmp_path: Path, monkeypatch: Any) -> None:
    """End-to-end CLI smoke test using a real built graph."""
    runner = CliRunner()
    repo = tmp_path / "demo"
    repo.mkdir()
    (repo / "a.py").write_text(
        "def foo(x):\n    return bar(x)\n\ndef bar(y):\n    return y\n"
    )
    monkeypatch.chdir(repo)
    # Build first
    result = runner.invoke(app, ["build", "--no-incremental"])
    assert result.exit_code == 0, result.output
    # Now trace
    result = runner.invoke(app, ["dataflow", "trace", "a.foo"])
    assert result.exit_code == 0, result.output
    assert "Flow trace from" in result.output


# ---- Test 12: CLI --format json ----
def test_cli_format_json(tmp_path: Path, monkeypatch: Any) -> None:
    runner = CliRunner()
    repo = tmp_path / "demo"
    repo.mkdir()
    (repo / "b.py").write_text(
        "def alpha():\n    return beta()\n\ndef beta():\n    return 1\n"
    )
    monkeypatch.chdir(repo)
    runner.invoke(app, ["build", "--no-incremental"])
    result = runner.invoke(app, ["dataflow", "trace", "b.alpha", "--format", "json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["entry"] == "b.alpha"
    assert "hops" in payload
    assert any(h["qualname"] == "b.alpha" for h in payload["hops"])


# ---- Test 13: MCP tool dataflow_trace ----
def test_mcp_dataflow_trace_tool() -> None:
    from codegraph.mcp_server.server import tool_dataflow_trace

    g: nx.MultiDiGraph = nx.MultiDiGraph()
    _add_func(g, "x.entry")
    _add_func(g, "x.target")
    _add_calls(g, "x.entry", "x.target", args=["v"])
    result = tool_dataflow_trace(g, entry="x.entry", depth=3)
    assert "error" not in result
    assert result["entry"] == "x.entry"
    qns = [h["qualname"] for h in result["hops"]]
    assert "x.entry" in qns
    assert "x.target" in qns


# ---- Test 14: MCP tool returns error for missing entry ----
def test_mcp_missing_entry_error() -> None:
    from codegraph.mcp_server.server import tool_dataflow_trace

    g: nx.MultiDiGraph = nx.MultiDiGraph()
    result = tool_dataflow_trace(g, entry="not.found", depth=3)
    assert "error" in result


# ---- Test 15: trace returns DataFlow even when only entry resolves ----
def test_trace_lone_entry_one_hop() -> None:
    g: nx.MultiDiGraph = nx.MultiDiGraph()
    _add_func(g, "lonely.fn")
    flow = trace(g, "lonely.fn")
    assert isinstance(flow, DataFlow)
    assert len(flow.hops) == 1
    assert flow.hops[0].qualname == "lonely.fn"
