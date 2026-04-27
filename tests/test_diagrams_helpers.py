"""Direct unit tests for codegraph.viz.diagrams._module_index."""
from __future__ import annotations

import networkx as nx

from codegraph.graph.schema import NodeKind
from codegraph.viz.diagrams import _module_index


def _make_graph() -> nx.MultiDiGraph:
    g = nx.MultiDiGraph()
    g.add_node(
        "m1",
        kind=NodeKind.MODULE,
        qualname="pkg.alpha",
        name="alpha",
        file="pkg/alpha.py",
        language="python",
        metadata={"is_test": False},
    )
    g.add_node(
        "f1",
        kind=NodeKind.FUNCTION,
        qualname="pkg.alpha.foo",
        name="foo",
        file="pkg/alpha.py",
        line_start=1,
        line_end=10,
    )
    g.add_node(
        "c1",
        kind=NodeKind.CLASS,
        qualname="pkg.alpha.Foo",
        name="Foo",
        file="pkg/alpha.py",
        line_start=11,
        line_end=20,
    )
    return g


def test_module_index_maps_module_to_itself() -> None:
    g = _make_graph()
    node_to_module, _info = _module_index(g)
    assert node_to_module["m1"] == "m1"


def test_module_index_maps_symbols_to_module_by_file() -> None:
    g = _make_graph()
    node_to_module, _ = _module_index(g)
    assert node_to_module["f1"] == "m1"
    assert node_to_module["c1"] == "m1"


def test_module_index_loc_is_max_line_end() -> None:
    g = _make_graph()
    _, info = _module_index(g)
    assert info["m1"]["loc"] == 20


def test_module_index_counts_symbols() -> None:
    g = _make_graph()
    _, info = _module_index(g)
    assert info["m1"]["symbols"] == 2


def test_module_index_extracts_package() -> None:
    g = _make_graph()
    _, info = _module_index(g)
    assert info["m1"]["package"] == "pkg"


def test_module_index_empty_graph() -> None:
    g = nx.MultiDiGraph()
    node_to_module, info = _module_index(g)
    assert node_to_module == {}
    assert info == {}


def test_module_index_skips_orphan_symbol_without_matching_file() -> None:
    g = _make_graph()
    g.add_node(
        "orphan",
        kind=NodeKind.FUNCTION,
        qualname="other.bar",
        name="bar",
        file="other/bar.py",
        line_start=1,
        line_end=5,
    )
    node_to_module, _ = _module_index(g)
    assert "orphan" not in node_to_module
