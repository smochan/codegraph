"""Tests for the embeddings soft-fail (v0.1.2 #10)."""
from __future__ import annotations

from pathlib import Path

import networkx as nx


def test_semantic_search_returns_not_built_when_index_missing(
    tmp_path: Path, monkeypatch
) -> None:
    from codegraph.mcp_server.server import tool_semantic_search

    monkeypatch.chdir(tmp_path)
    result = tool_semantic_search(nx.MultiDiGraph(), "x", k=5)
    assert result["status"] == "embeddings_not_built"
    assert "codegraph embed" in result["message"]
    assert "Structural query tools" in result["message"]


def test_hybrid_search_returns_not_built_when_index_missing(
    tmp_path: Path, monkeypatch
) -> None:
    from codegraph.mcp_server.server import tool_hybrid_search

    monkeypatch.chdir(tmp_path)
    result = tool_hybrid_search(nx.MultiDiGraph(), "x", k=5)
    assert result["status"] == "embeddings_not_built"
    assert "Structural query tools" in result["message"]


def test_not_enabled_status_when_import_fails(tmp_path: Path, monkeypatch) -> None:
    """When `codegraph.embed.query` can't be imported, return not_enabled."""
    import sys

    from codegraph.mcp_server.server import tool_semantic_search

    # Force the import to fail by inserting a sentinel that raises.
    class _FailModule:
        def __getattr__(self, name: str) -> object:
            raise ImportError(f"simulated missing dep: {name}")

    # The function does `from codegraph.embed.query import ...`. To make
    # that fail, replace the parent `codegraph.embed.query` in sys.modules
    # with one that raises on attribute access. The `from ... import` form
    # triggers `__getattr__` on the module.
    monkeypatch.setitem(sys.modules, "codegraph.embed.query", _FailModule())
    monkeypatch.chdir(tmp_path)
    result = tool_semantic_search(nx.MultiDiGraph(), "x", k=5)
    assert result["status"] == "embeddings_not_enabled"
    assert "pip install polycodegraph[embed]" in result["message"]
