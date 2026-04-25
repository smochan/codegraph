"""Smoke tests for the codegraph web dashboard server."""
from __future__ import annotations

import json
import threading
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import networkx as nx
import pytest

from codegraph.viz.dashboard import build_dashboard_payload
from codegraph.web.server import DashboardState, _Handler


def _tiny_graph() -> nx.MultiDiGraph:
    g: nx.MultiDiGraph = nx.MultiDiGraph()
    g.add_node("a.py:foo", kind="function", file="a.py", qualname="a.foo",
               name="foo", language="python", loc=3)
    g.add_node("b.py:bar", kind="function", file="b.py", qualname="b.bar",
               name="bar", language="python", loc=2)
    g.add_edge("a.py:foo", "b.py:bar", kind="CALLS")
    return g


def test_build_dashboard_payload_keys() -> None:
    payload = build_dashboard_payload(_tiny_graph())
    for key in ("metrics", "issues", "hotspots", "matrix", "sankey",
                "treemap", "flows", "files", "hld"):
        assert key in payload
    assert payload["metrics"]["nodes"] == 2
    assert payload["metrics"]["edges"] == 1


@pytest.fixture
def server(tmp_path: Path) -> tuple[ThreadingHTTPServer, str]:
    state = DashboardState(
        repo_root=tmp_path,
        explore_dir=tmp_path / "explore",
        graph_loader=_tiny_graph,
    )
    handler_cls = type("_TestHandler", (_Handler,), {"state": state})
    srv = ThreadingHTTPServer(("127.0.0.1", 0), handler_cls)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    yield srv, base
    srv.shutdown()


def test_serves_index(server: tuple[ThreadingHTTPServer, str]) -> None:
    _, base = server
    with urllib.request.urlopen(f"{base}/") as resp:
        assert resp.status == 200
        body = resp.read().decode("utf-8")
    assert "<html" in body.lower()


def test_api_data(server: tuple[ThreadingHTTPServer, str]) -> None:
    _, base = server
    with urllib.request.urlopen(f"{base}/api/data.json") as resp:
        data = json.loads(resp.read())
    assert data["metrics"]["nodes"] == 2
    assert data["repo"]  # repo name attached by server


def test_path_traversal_blocked(server: tuple[ThreadingHTTPServer, str]) -> None:
    _, base = server
    req = urllib.request.Request(f"{base}/../../etc/passwd")
    try:
        urllib.request.urlopen(req)
    except urllib.error.HTTPError as exc:
        assert exc.code == 404
    else:
        pytest.fail("expected 404")


def test_rebuild_endpoint(server: tuple[ThreadingHTTPServer, str]) -> None:
    _, base = server
    req = urllib.request.Request(f"{base}/api/rebuild", method="POST", data=b"")
    with urllib.request.urlopen(req) as resp:
        data = json.loads(resp.read())
    assert data == {"ok": True}
