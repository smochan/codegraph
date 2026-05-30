"""Tests for the external/unresolved-local edge classification (v0.1.2 #2)."""
from __future__ import annotations

import networkx as nx

from codegraph.analysis.metrics import _module_root, compute_metrics


def test_module_root_handles_separators() -> None:
    assert _module_root("foo.bar.baz") == "foo"
    assert _module_root("pkg/sub/file") == "pkg"
    assert _module_root("a::b") == "a"
    assert _module_root("simple") == "simple"
    assert _module_root("") == ""


def _make_graph_with_module(module_qualname: str) -> nx.MultiDiGraph:
    g = nx.MultiDiGraph()
    g.add_node(
        "mod:" + module_qualname,
        kind="MODULE",
        qualname=module_qualname,
        language="python",
    )
    g.add_node(
        "fn:caller",
        kind="FUNCTION",
        qualname=module_qualname + ".caller",
        language="python",
    )
    return g


def test_external_vs_unresolved_local_classification() -> None:
    g = _make_graph_with_module("myrepo")

    # External: target root is `fastapi`, not in repo
    g.add_edge("fn:caller", "unresolved::fastapi.FastAPI", kind="IMPORTS")
    # External: target root is `os`, not in repo
    g.add_edge("fn:caller", "unresolved::os.path.join", kind="CALLS")
    # Local-unresolved: target root is `myrepo`, IS in repo
    g.add_edge("fn:caller", "unresolved::myrepo.utils.missing_fn", kind="CALLS")
    # Bare name with no dot: treated as external since root not in repo_roots
    g.add_edge("fn:caller", "unresolved::randomBareName", kind="CALLS")

    m = compute_metrics(g)
    assert m.external_edges == 3
    assert m.unresolved_local_edges == 1
    # Back-compat field is the sum.
    assert m.unresolved_edges == 4


def test_no_modules_means_everything_external() -> None:
    g = nx.MultiDiGraph()
    g.add_node("fn:x", kind="FUNCTION", qualname="x")
    g.add_edge("fn:x", "unresolved::anything", kind="CALLS")
    m = compute_metrics(g)
    assert m.external_edges == 1
    assert m.unresolved_local_edges == 0


def test_no_unresolved_edges_yields_zero_external() -> None:
    g = _make_graph_with_module("myrepo")
    g.add_node("fn:other", kind="FUNCTION", qualname="myrepo.other")
    g.add_edge("fn:caller", "fn:other", kind="CALLS")
    m = compute_metrics(g)
    assert m.external_edges == 0
    assert m.unresolved_local_edges == 0
    assert m.unresolved_edges == 0
