"""Tests for DF0/DF1.5 metadata in MCP tool responses."""
from __future__ import annotations

from typing import Any

import networkx as nx
import pytest


def _build_graph(
    *,
    foo_md: dict[str, Any] | None = None,
    bar_md: dict[str, Any] | None = None,
    call_md: dict[str, Any] | None = None,
) -> nx.MultiDiGraph:
    g: nx.MultiDiGraph = nx.MultiDiGraph()
    g.add_node(
        "foo_id",
        kind="FUNCTION",
        qualname="pkg.foo",
        name="foo",
        file="pkg/a.py",
        line_start=1,
        metadata=foo_md or {},
    )
    g.add_node(
        "bar_id",
        kind="FUNCTION",
        qualname="pkg.bar",
        name="bar",
        file="pkg/b.py",
        line_start=2,
        metadata=bar_md or {},
    )
    g.add_edge(
        "foo_id",
        "bar_id",
        key="CALLS",
        kind="CALLS",
        metadata=call_md or {},
    )
    return g


def test_find_symbol_includes_params_returns_role() -> None:
    from codegraph.mcp_server.server import tool_find_symbol

    g = _build_graph(
        foo_md={
            "params": [{"name": "x", "type": "int", "default": None}],
            "returns": "str",
            "role": "HANDLER",
        }
    )
    results = tool_find_symbol(g, query="foo")
    assert len(results) == 1
    hit = results[0]
    assert hit["params"] == [{"name": "x", "type": "int", "default": None}]
    assert hit["returns"] == "str"
    assert hit["role"] == "HANDLER"


def test_find_symbol_role_filter_matches() -> None:
    from codegraph.mcp_server.server import tool_find_symbol

    g = _build_graph(
        foo_md={"role": "HANDLER"},
        bar_md={"role": "SERVICE"},
    )
    results = tool_find_symbol(g, query="pkg", role="HANDLER")
    assert len(results) == 1
    assert results[0]["qualname"] == "pkg.foo"


def test_find_symbol_role_filter_no_matches() -> None:
    from codegraph.mcp_server.server import tool_find_symbol

    g = _build_graph(foo_md={"role": "SERVICE"}, bar_md={"role": "REPO"})
    results = tool_find_symbol(g, query="pkg", role="HANDLER")
    assert results == []


def test_callees_includes_target_metadata_and_call_args() -> None:
    from codegraph.mcp_server.server import tool_callees

    g = _build_graph(
        bar_md={
            "params": [{"name": "n", "type": "int", "default": None}],
            "role": "SERVICE",
        },
        call_md={"args": ["1"], "kwargs": {"k": "True"}},
    )
    results = tool_callees(g, qualname="pkg.foo")
    assert len(results) == 1
    entry = results[0]
    assert entry["qualname"] == "pkg.bar"
    assert entry["params"] == [{"name": "n", "type": "int", "default": None}]
    assert entry["role"] == "SERVICE"
    assert entry["args"] == ["1"]
    assert entry["kwargs"] == {"k": "True"}


def test_callers_includes_source_metadata_and_call_args() -> None:
    from codegraph.mcp_server.server import tool_callers

    g = _build_graph(
        foo_md={
            "params": [{"name": "x", "type": "int", "default": None}],
            "role": "HANDLER",
        },
        call_md={"args": ["42"], "kwargs": {}},
    )
    results = tool_callers(g, qualname="pkg.bar")
    assert len(results) == 1
    entry = results[0]
    assert entry["qualname"] == "pkg.foo"
    assert entry["params"] == [{"name": "x", "type": "int", "default": None}]
    assert entry["role"] == "HANDLER"
    assert entry["args"] == ["42"]


def test_backwards_compat_no_metadata_no_keys() -> None:
    from codegraph.mcp_server.server import (
        tool_callees,
        tool_callers,
        tool_find_symbol,
    )

    g = _build_graph()  # no metadata anywhere
    fs = tool_find_symbol(g, query="pkg.foo")
    assert len(fs) == 1
    hit = fs[0]
    assert "params" not in hit
    assert "returns" not in hit
    assert "role" not in hit
    assert set(hit.keys()) == {"qualname", "kind", "file", "line"}

    cees = tool_callees(g, qualname="pkg.foo")
    assert len(cees) == 1
    assert "params" not in cees[0]
    assert "role" not in cees[0]
    assert "args" not in cees[0]
    assert "kwargs" not in cees[0]

    crs = tool_callers(g, qualname="pkg.bar")
    assert len(crs) == 1
    assert "role" not in crs[0]


def test_find_symbol_role_in_schema() -> None:
    from codegraph.mcp_server.server import tool_registry

    _fn, schema = tool_registry["find_symbol"]
    props = schema["properties"]
    assert "role" in props
    assert props["role"]["enum"] == ["HANDLER", "SERVICE", "COMPONENT", "REPO"]


@pytest.mark.parametrize("role", ["HANDLER", "SERVICE", "COMPONENT", "REPO"])
def test_find_symbol_role_filter_each_role(role: str) -> None:
    from codegraph.mcp_server.server import tool_find_symbol

    g = _build_graph(foo_md={"role": role})
    results = tool_find_symbol(g, query="pkg.foo", role=role)
    assert len(results) == 1
    assert results[0]["role"] == role
