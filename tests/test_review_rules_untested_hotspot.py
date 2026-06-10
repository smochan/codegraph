"""Tests for the new_untested_hotspot review rule."""
from __future__ import annotations

import shutil
from pathlib import Path

import networkx as nx
import pytest

from codegraph.graph.builder import GraphBuilder
from codegraph.graph.store_networkx import to_digraph
from codegraph.graph.store_sqlite import SQLiteGraphStore
from codegraph.review.differ import diff_graphs
from codegraph.review.rules import DEFAULT_RULES, Rule, evaluate_rules

FIXTURES = Path(__file__).parent / "fixtures"


def _build_graph(repo: Path, db_path: Path) -> nx.MultiDiGraph:
    store = SQLiteGraphStore(db_path)
    GraphBuilder(repo, store).build(incremental=False)
    g = to_digraph(store)
    store.close()
    return g


@pytest.fixture
def hotspot_graphs(
    tmp_path: Path,
) -> tuple[nx.MultiDiGraph, nx.MultiDiGraph]:
    """v1 → v2: v2 adds hot_helper with 5 callers but no test coverage."""
    old_repo = tmp_path / "old"
    new_repo = tmp_path / "new"
    old_repo.mkdir()
    new_repo.mkdir()
    shutil.copytree(FIXTURES / "python_hotspot_v1", old_repo / "pkg")
    shutil.copytree(FIXTURES / "python_hotspot_v2", new_repo / "pkg")
    old_g = _build_graph(old_repo, tmp_path / "old.db")
    new_g = _build_graph(new_repo, tmp_path / "new.db")
    return old_g, new_g


@pytest.fixture
def hotspot_tested_graphs(
    tmp_path: Path,
) -> tuple[nx.MultiDiGraph, nx.MultiDiGraph]:
    """v1 → v2_tested: same as above but v2 test suite does call hot_helper."""
    old_repo = tmp_path / "old"
    new_repo = tmp_path / "new"
    old_repo.mkdir()
    new_repo.mkdir()
    shutil.copytree(FIXTURES / "python_hotspot_v1", old_repo / "pkg")
    shutil.copytree(FIXTURES / "python_hotspot_v2_tested", new_repo / "pkg")
    old_g = _build_graph(old_repo, tmp_path / "old.db")
    new_g = _build_graph(new_repo, tmp_path / "new.db")
    return old_g, new_g


class TestNewUntestedHotspotRule:
    def test_rule_fires_for_high_fan_in_new_function(
        self,
        hotspot_graphs: tuple[nx.MultiDiGraph, nx.MultiDiGraph],
    ) -> None:
        """Rule fires when a new function has >= 5 callers and no test coverage."""
        old_g, new_g = hotspot_graphs
        diff = diff_graphs(old_g, new_g)
        rules = [
            Rule(
                id="new-untested-hotspot",
                when="new_untested_hotspot",
                severity="high",
                message="New function with {fan_in} callers and no test coverage",
                threshold=5,
            )
        ]
        findings = evaluate_rules(diff, new_graph=new_g, old_graph=old_g, rules=rules)
        matching = [f for f in findings if f.rule_id == "new-untested-hotspot"]
        assert matching, "Expected the rule to fire for hot_helper"
        assert any("hot_helper" in f.qualname for f in matching)

    def test_rule_suppressed_by_test_caller(
        self,
        hotspot_tested_graphs: tuple[nx.MultiDiGraph, nx.MultiDiGraph],
    ) -> None:
        """Rule does not fire when the test suite already calls hot_helper."""
        old_g, new_g = hotspot_tested_graphs
        diff = diff_graphs(old_g, new_g)
        rules = [
            Rule(
                id="new-untested-hotspot",
                when="new_untested_hotspot",
                severity="high",
                message="New function with {fan_in} callers and no test coverage",
                threshold=5,
            )
        ]
        findings = evaluate_rules(diff, new_graph=new_g, old_graph=old_g, rules=rules)
        matching = [f for f in findings if f.rule_id == "new-untested-hotspot"]
        assert not any(
            "hot_helper" in f.qualname for f in matching
        ), "Rule should be suppressed when test module calls hot_helper"

    def test_rule_in_default_rules(self) -> None:
        """Confirm new-untested-hotspot is in DEFAULT_RULES."""
        ids = [r.id for r in DEFAULT_RULES]
        assert "new-untested-hotspot" in ids

    def test_threshold_below_five_does_not_fire(
        self,
        hotspot_graphs: tuple[nx.MultiDiGraph, nx.MultiDiGraph],
    ) -> None:
        """With threshold=10 the rule should not fire (only 5 callers)."""
        old_g, new_g = hotspot_graphs
        diff = diff_graphs(old_g, new_g)
        rules = [
            Rule(
                id="new-untested-hotspot",
                when="new_untested_hotspot",
                severity="high",
                message="New function with {fan_in} callers and no test coverage",
                threshold=10,
            )
        ]
        findings = evaluate_rules(diff, new_graph=new_g, old_graph=old_g, rules=rules)
        matching = [f for f in findings if f.rule_id == "new-untested-hotspot"]
        assert not matching, "With threshold=10, 5 callers should not trigger rule"
