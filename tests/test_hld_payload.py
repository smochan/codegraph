"""Tests for DF0/DF1.5 metadata surfacing in the HLD payload.

Decision on missing fields: when a node lacks ``params``/``returns``/``role``
in its metadata, the corresponding key is OMITTED from the symbol payload
(no ``null``/empty placeholders). ``callee_args`` is also omitted when there
are no callees, but each entry uses ``{"args": [], "kwargs": {}}`` to keep
index alignment when at least one callee exists.
"""
from __future__ import annotations

from typing import Any

import networkx as nx
import pytest

from codegraph.viz.hld import build_hld


def _make_graph(
    *,
    pkg_root: str = "pkg",
    foo_metadata: dict[str, Any] | None = None,
    bar_metadata: dict[str, Any] | None = None,
    call_edge_metadata: dict[str, Any] | None = None,
    add_call_edge: bool = True,
) -> nx.MultiDiGraph:
    """Build a minimal graph with one module + two functions and (optionally) a CALLS edge."""
    g: nx.MultiDiGraph = nx.MultiDiGraph()
    g.add_node(
        "mod_id",
        kind="MODULE",
        qualname=f"{pkg_root}.module_a",
        name="module_a",
        file=f"{pkg_root}/module_a.py",
        line_start=1,
        metadata={},
    )
    g.add_node(
        "foo_id",
        kind="FUNCTION",
        qualname=f"{pkg_root}.module_a.foo",
        name="foo",
        file=f"{pkg_root}/module_a.py",
        line_start=10,
        metadata=foo_metadata or {},
    )
    g.add_node(
        "bar_id",
        kind="FUNCTION",
        qualname=f"{pkg_root}.module_a.bar",
        name="bar",
        file=f"{pkg_root}/module_a.py",
        line_start=20,
        metadata=bar_metadata or {},
    )
    if add_call_edge:
        g.add_edge(
            "foo_id",
            "bar_id",
            key="CALLS",
            kind="CALLS",
            metadata=call_edge_metadata or {},
        )
    return g


def _symbol(payload: Any, qualname: str) -> dict[str, Any]:
    for module in payload.modules.values():
        for sym in module["symbols"]:
            if sym["qualname"] == qualname:
                return sym
    raise AssertionError(f"symbol {qualname!r} not in payload")


def test_params_surfaces_when_present() -> None:
    g = _make_graph(
        foo_metadata={
            "params": [
                {"name": "x", "type": "int", "default": None},
                {"name": "y", "type": "str", "default": "'hi'"},
            ],
        },
    )
    payload = build_hld(g)
    sym = _symbol(payload, "pkg.module_a.foo")
    assert sym["params"] == [
        {"name": "x", "type": "int", "default": None},
        {"name": "y", "type": "str", "default": "'hi'"},
    ]


def test_params_omitted_when_absent() -> None:
    g = _make_graph()  # neither node has metadata
    payload = build_hld(g)
    sym = _symbol(payload, "pkg.module_a.foo")
    assert "params" not in sym
    assert "returns" not in sym
    assert "role" not in sym


def test_returns_surfaces_when_present() -> None:
    g = _make_graph(foo_metadata={"returns": "Response"})
    payload = build_hld(g)
    sym = _symbol(payload, "pkg.module_a.foo")
    assert sym["returns"] == "Response"


@pytest.mark.parametrize("role", ["HANDLER", "SERVICE", "COMPONENT", "REPO"])
def test_role_surfaces_for_each_value(role: str) -> None:
    g = _make_graph(foo_metadata={"role": role})
    payload = build_hld(g)
    sym = _symbol(payload, "pkg.module_a.foo")
    assert sym["role"] == role


def test_role_none_omitted() -> None:
    g = _make_graph(foo_metadata={"role": None})
    payload = build_hld(g)
    sym = _symbol(payload, "pkg.module_a.foo")
    assert "role" not in sym


def test_callee_args_index_aligned_with_callees() -> None:
    g = _make_graph(
        call_edge_metadata={"args": ["1", "x"], "kwargs": {"name": '"bob"'}},
    )
    payload = build_hld(g)
    sym = _symbol(payload, "pkg.module_a.foo")
    assert sym["callees"] == ["pkg.module_a.bar"]
    assert sym["callee_args"] == [
        {"args": ["1", "x"], "kwargs": {"name": '"bob"'}}
    ]


def test_callee_args_empty_placeholder_when_edge_has_no_metadata() -> None:
    g = _make_graph(call_edge_metadata={})
    payload = build_hld(g)
    sym = _symbol(payload, "pkg.module_a.foo")
    assert sym["callees"] == ["pkg.module_a.bar"]
    assert sym["callee_args"] == [{"args": [], "kwargs": {}}]


def test_callee_args_omitted_when_no_callees() -> None:
    g = _make_graph(add_call_edge=False)
    payload = build_hld(g)
    sym = _symbol(payload, "pkg.module_a.foo")
    assert sym["callees"] == []
    assert "callee_args" not in sym
