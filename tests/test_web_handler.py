"""Tests for codegraph.web.server DashboardState._build_payload and _Handler._send_bytes."""
from __future__ import annotations

import io
from pathlib import Path
from unittest.mock import MagicMock

import networkx as nx

from codegraph.graph.builder import GraphBuilder
from codegraph.graph.schema import EdgeKind, NodeKind
from codegraph.graph.store_networkx import to_digraph
from codegraph.graph.store_sqlite import SQLiteGraphStore
from codegraph.web.server import DashboardState, _Handler


def _build_small_graph(tmp_path: Path) -> nx.MultiDiGraph:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "m.py").write_text("def f():\n    return 1\n", encoding="utf-8")
    db = tmp_path / "graph.db"
    store = SQLiteGraphStore(db)
    GraphBuilder(repo, store).build(incremental=False)
    g = to_digraph(store)
    store.close()
    return g


# ---------- DashboardState._build_payload ----------

def test_build_payload_includes_metrics_repo_built_at(tmp_path: Path) -> None:
    g = _build_small_graph(tmp_path)
    state = DashboardState(
        repo_root=tmp_path / "repo",
        explore_dir=tmp_path / "explore",
        graph_loader=lambda: g,
    )
    payload = state._build_payload(g)
    assert "metrics" in payload
    assert payload["repo"] == "repo"
    assert "built_at" in payload
    assert isinstance(payload["built_at"], str)


def test_build_payload_metrics_have_node_and_edge_counts(tmp_path: Path) -> None:
    g = _build_small_graph(tmp_path)
    state = DashboardState(
        repo_root=tmp_path / "repo",
        explore_dir=tmp_path / "explore",
        graph_loader=lambda: g,
    )
    payload = state._build_payload(g)
    metrics = payload["metrics"]
    assert "nodes" in metrics
    assert "edges" in metrics
    assert metrics["nodes"] >= 0
    assert metrics["edges"] >= 0


def test_payload_caches_first_build(tmp_path: Path) -> None:
    g = _build_small_graph(tmp_path)
    calls = {"n": 0}

    def loader() -> nx.MultiDiGraph:
        calls["n"] += 1
        return g

    state = DashboardState(
        repo_root=tmp_path / "repo",
        explore_dir=tmp_path / "explore",
        graph_loader=loader,
    )
    state.payload()
    state.payload()
    assert calls["n"] == 1


# ---------- _Handler._send_bytes ----------

class _FakeHandler:
    """Subset of _Handler used to drive _send_bytes without sockets."""
    def __init__(self) -> None:
        self.send_response = MagicMock()
        self.send_header = MagicMock()
        self.end_headers = MagicMock()
        self.wfile = io.BytesIO()


def test_send_bytes_writes_status_headers_body() -> None:
    fake = _FakeHandler()
    body = b"hello world"
    _Handler._send_bytes(fake, body, "text/plain", 200)  # type: ignore[arg-type]

    fake.send_response.assert_called_once_with(200)
    headers = {call.args[0]: call.args[1] for call in fake.send_header.call_args_list}
    assert headers["Content-Type"] == "text/plain"
    assert headers["Content-Length"] == str(len(body))
    assert headers["Cache-Control"] == "no-store"
    fake.end_headers.assert_called_once()
    assert fake.wfile.getvalue() == body


def test_send_bytes_default_status_is_200() -> None:
    fake = _FakeHandler()
    _Handler._send_bytes(fake, b"x", "application/json")  # type: ignore[arg-type]
    fake.send_response.assert_called_once_with(200)


def test_send_bytes_propagates_custom_status() -> None:
    fake = _FakeHandler()
    _Handler._send_bytes(fake, b"missing", "text/plain", 404)  # type: ignore[arg-type]
    fake.send_response.assert_called_once_with(404)


def test_send_bytes_sets_correct_content_length_for_unicode() -> None:
    fake = _FakeHandler()
    body = "café 🚀".encode()
    _Handler._send_bytes(fake, body, "text/plain; charset=utf-8")  # type: ignore[arg-type]
    headers = {call.args[0]: call.args[1] for call in fake.send_header.call_args_list}
    assert headers["Content-Length"] == str(len(body))
    assert fake.wfile.getvalue() == body


def test_send_bytes_handles_empty_body() -> None:
    fake = _FakeHandler()
    _Handler._send_bytes(fake, b"", "text/plain")  # type: ignore[arg-type]
    headers = {call.args[0]: call.args[1] for call in fake.send_header.call_args_list}
    assert headers["Content-Length"] == "0"
    assert fake.wfile.getvalue() == b""


def test_module_imports_have_expected_kinds() -> None:
    """Sanity: schema enums are still in place."""
    assert NodeKind.MODULE.value == "MODULE"
    assert EdgeKind.CALLS.value == "CALLS"
