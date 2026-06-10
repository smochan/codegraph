"""Tests for rank_untested and the enriched UntestedNode fields."""
from __future__ import annotations

import networkx as nx

from codegraph.analysis.untested import find_untested, rank_untested
from codegraph.graph.schema import EdgeKind, NodeKind


def _make_graph() -> nx.MultiDiGraph:
    """Build a minimal graph with two untested functions:

    - ``hot_func``: 3 incoming CALLS (high fan-in, high hotspot)
    - ``cold_func``: 0 incoming CALLS (zero fan-in, low hotspot)

    Neither has any caller from a test module, so both are untested.
    """
    g: nx.MultiDiGraph = nx.MultiDiGraph()

    # The two untested functions
    g.add_node(
        "hot_func",
        kind=NodeKind.FUNCTION.value,
        name="hot_func",
        qualname="pkg.hot_func",
        file="pkg/core.py",
        line_start=10,
        line_end=30,
        metadata={},
    )
    g.add_node(
        "cold_func",
        kind=NodeKind.FUNCTION.value,
        name="cold_func",
        qualname="pkg.cold_func",
        file="pkg/core.py",
        line_start=35,
        line_end=40,
        metadata={},
    )

    # Three non-test callers of hot_func
    for i in range(3):
        caller_id = f"caller_{i}"
        g.add_node(
            caller_id,
            kind=NodeKind.FUNCTION.value,
            name=f"caller_{i}",
            qualname=f"pkg.caller_{i}",
            file="pkg/callers.py",
            line_start=i * 10 + 1,
            line_end=i * 10 + 5,
            metadata={},
        )
        g.add_edge(caller_id, "hot_func", key=EdgeKind.CALLS.value, kind=EdgeKind.CALLS.value)

    return g


def _make_graph_with_test_caller() -> nx.MultiDiGraph:
    """Same as _make_graph but adds a test-module caller for hot_func."""
    g = _make_graph()
    g.add_node(
        "test_hot_func",
        kind=NodeKind.FUNCTION.value,
        name="test_hot_func",
        qualname="tests.test_core.test_hot_func",
        file="tests/test_core.py",
        line_start=1,
        line_end=5,
        metadata={"is_test": True},
    )
    g.add_edge(
        "test_hot_func", "hot_func",
        key=EdgeKind.CALLS.value, kind=EdgeKind.CALLS.value,
    )
    return g


class TestRankUntested:
    def test_hot_func_ranks_above_cold_func(self) -> None:
        g = _make_graph()
        ranked = rank_untested(g)
        qualnames = [u.qualname for u in ranked]
        assert "pkg.hot_func" in qualnames
        assert "pkg.cold_func" in qualnames
        hot_idx = qualnames.index("pkg.hot_func")
        cold_idx = qualnames.index("pkg.cold_func")
        assert hot_idx < cold_idx, "hot_func must rank above cold_func"

    def test_hotspot_score_populated(self) -> None:
        g = _make_graph()
        ranked = rank_untested(g)
        hot = next(u for u in ranked if u.qualname == "pkg.hot_func")
        # fan_in=3, fan_out=0, loc=(30-10+1)=21 -> score = 3*2 + 0 + 21//50 = 6
        assert hot.hotspot_score == 6
        cold = next(u for u in ranked if u.qualname == "pkg.cold_func")
        # fan_in=0, fan_out=0, loc=(40-35+1)=6 -> score = 0
        assert cold.hotspot_score == 0

    def test_blast_radius_populated_for_hot_func(self) -> None:
        g = _make_graph()
        ranked = rank_untested(g)
        hot = next(u for u in ranked if u.qualname == "pkg.hot_func")
        # 3 direct callers should be in blast radius
        assert hot.blast_radius_size >= 3
        assert hot.blast_files >= 1

    def test_blast_radius_zero_for_cold_func(self) -> None:
        g = _make_graph()
        ranked = rank_untested(g)
        cold = next(u for u in ranked if u.qualname == "pkg.cold_func")
        # cold_func has no callers, blast radius skipped -> 0
        assert cold.blast_radius_size == 0
        assert cold.blast_files == 0

    def test_top_parameter_truncates(self) -> None:
        g = _make_graph()
        ranked = rank_untested(g, top=1)
        assert len(ranked) == 1
        assert ranked[0].qualname == "pkg.hot_func"

    def test_find_untested_not_affected(self) -> None:
        """find_untested still works and new fields default to 0."""
        g = _make_graph()
        rows = find_untested(g)
        for row in rows:
            assert row.hotspot_score == 0
            assert row.blast_radius_size == 0
            assert row.blast_files == 0

    def test_test_caller_removes_from_untested(self) -> None:
        """When a test module calls hot_func it is no longer untested."""
        g = _make_graph_with_test_caller()
        ranked = rank_untested(g)
        qualnames = [u.qualname for u in ranked]
        assert "pkg.hot_func" not in qualnames
        assert "pkg.cold_func" in qualnames
