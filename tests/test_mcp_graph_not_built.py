"""Tests for the actionable graph-not-built MCP error (v0.1.2 #8).

Pre-0.1.2 the MCP server would happily return an empty graph if the
db didn't exist; Claude/Cursor paraphrased this as "workspace is empty"
which sent users down the wrong rabbit hole. 0.1.2 returns a structured
``{error: graph_not_built, message: ...}`` so the LLM can quote the
exact `codegraph build` command back to the user.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from codegraph.mcp_server.server import (
    GraphNotBuiltError,
    _load_graph,
)


def test_load_graph_raises_when_db_missing(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    # Reset module-level cache so this test isn't contaminated by prior runs.
    import codegraph.mcp_server.server as srv
    srv._CACHED_GRAPH = None
    srv._CACHED_DB_PATH = None
    with pytest.raises(GraphNotBuiltError) as exc_info:
        _load_graph(None)
    assert exc_info.value.db_path == tmp_path / ".codegraph" / "graph.db"


def test_dispatch_returns_actionable_error_when_db_missing(
    tmp_path: Path, monkeypatch
) -> None:
    """End-to-end-ish: invoke the dispatch and assert the JSON shape."""
    monkeypatch.chdir(tmp_path)
    import codegraph.mcp_server.server as srv
    srv._CACHED_GRAPH = None
    srv._CACHED_DB_PATH = None

    server = srv._build_server("test")
    # The decorated handler is the one we want — pull it from the registry.
    # mcp.Server stores tool handlers internally; easiest path: call the
    # exposed pure handler directly with a load-stub. Instead we trust
    # the load_graph raise + dispatch glue tested as a unit:
    import asyncio

    async def _invoke() -> str:
        # Use the same mechanism the server uses: the `request_handlers`
        # dict carries the call-tool function under `types.CallToolRequest`.
        from mcp import types

        handler = server.request_handlers[types.CallToolRequest]
        req = types.CallToolRequest(
            method="tools/call",
            params=types.CallToolRequestParams(
                name="find_symbol", arguments={"query": "x"},
            ),
        )
        resp = await handler(req)
        content = resp.root.content[0]
        return content.text

    text = asyncio.run(_invoke())
    payload = json.loads(text)
    assert payload["error"] == "graph_not_built"
    assert "codegraph build" in payload["message"]
    assert "db_path" in payload
