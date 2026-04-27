"""Tests for analyzer noise reduction (C2)."""
from __future__ import annotations

import networkx as nx

from codegraph.analysis import find_dead_code, find_untested
from codegraph.graph.schema import EdgeKind, NodeKind


def _add_module(g: nx.MultiDiGraph, mod_id: str, file_path: str) -> None:
    g.add_node(
        mod_id,
        kind=NodeKind.MODULE.value,
        name=file_path.rsplit("/", 1)[-1],
        qualname=file_path,
        file=file_path,
        line_start=0,
        language="python",
        metadata={},
    )


def _add_function(
    g: nx.MultiDiGraph,
    fn_id: str,
    name: str,
    qualname: str,
    file_path: str,
    *,
    kind: str = NodeKind.FUNCTION.value,
    metadata: dict[str, object] | None = None,
) -> None:
    g.add_node(
        fn_id,
        kind=kind,
        name=name,
        qualname=qualname,
        file=file_path,
        line_start=1,
        language="python",
        metadata=metadata or {},
    )


def _add_defined_in(g: nx.MultiDiGraph, child_id: str, parent_id: str) -> None:
    g.add_edge(
        child_id,
        parent_id,
        key=EdgeKind.DEFINED_IN.value,
        kind=EdgeKind.DEFINED_IN.value,
        metadata={},
    )


# ----- Fixture-path exclusion --------------------------------------------


def test_untested_skips_test_fixture_files() -> None:
    g: nx.MultiDiGraph = nx.MultiDiGraph()
    _add_module(g, "mod::fix", "tests/fixtures/sample/sample.py")
    _add_function(
        g,
        "fn::fixture_helper",
        "fixture_helper",
        "tests.fixtures.sample.sample.fixture_helper",
        "tests/fixtures/sample/sample.py",
    )
    _add_defined_in(g, "fn::fixture_helper", "mod::fix")

    untested_qualnames = {u.qualname for u in find_untested(g)}
    assert not any(
        "fixture_helper" in q for q in untested_qualnames
    ), f"Fixture function should be skipped: {untested_qualnames}"


def test_untested_still_flags_real_source_files() -> None:
    g: nx.MultiDiGraph = nx.MultiDiGraph()
    _add_module(g, "mod::src", "src/pkg/svc.py")
    _add_function(
        g,
        "fn::compute",
        "compute",
        "pkg.svc.compute",
        "src/pkg/svc.py",
    )
    _add_defined_in(g, "fn::compute", "mod::src")

    untested_qualnames = {u.qualname for u in find_untested(g)}
    assert "pkg.svc.compute" in untested_qualnames


def test_dead_code_still_uses_shared_path_exclusion() -> None:
    """Dead-code analyzer continues to skip fixture-path nodes after the move."""
    g: nx.MultiDiGraph = nx.MultiDiGraph()
    _add_module(g, "mod::fix", "tests/fixtures/sample/sample.py")
    _add_function(
        g,
        "fn::fixture_helper",
        "fixture_helper",
        "tests.fixtures.sample.sample.fixture_helper",
        "tests/fixtures/sample/sample.py",
    )
    _add_defined_in(g, "fn::fixture_helper", "mod::fix")

    dead_qualnames = {d.qualname for d in find_dead_code(g)}
    assert not any("fixture_helper" in q for q in dead_qualnames)
