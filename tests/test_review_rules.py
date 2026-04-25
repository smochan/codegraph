"""Tests for codegraph.review.rules."""
from __future__ import annotations

import shutil
from pathlib import Path

import networkx as nx
import pytest

from codegraph.graph.builder import GraphBuilder
from codegraph.graph.store_networkx import to_digraph
from codegraph.graph.store_sqlite import SQLiteGraphStore
from codegraph.review.differ import diff_graphs
from codegraph.review.rules import (
    DEFAULT_RULES,
    Rule,
    evaluate_rules,
    load_rules,
)

FIXTURES = Path(__file__).parent / "fixtures"


def _build_graph(repo: Path, db_path: Path) -> nx.MultiDiGraph:
    store = SQLiteGraphStore(db_path)
    GraphBuilder(repo, store).build(incremental=False)
    g = to_digraph(store)
    store.close()
    return g


@pytest.fixture
def graphs(tmp_path: Path) -> tuple[nx.MultiDiGraph, nx.MultiDiGraph]:
    old_repo = tmp_path / "old"
    new_repo = tmp_path / "new"
    old_repo.mkdir()
    new_repo.mkdir()
    shutil.copytree(FIXTURES / "python_sample", old_repo / "pkg")
    shutil.copytree(FIXTURES / "python_sample_v2", new_repo / "pkg")
    old_g = _build_graph(old_repo, tmp_path / "old.db")
    new_g = _build_graph(new_repo, tmp_path / "new.db")
    return old_g, new_g


def test_default_rules_run_on_real_diff(
    graphs: tuple[nx.MultiDiGraph, nx.MultiDiGraph],
) -> None:
    old_g, new_g = graphs
    diff = diff_graphs(old_g, new_g)
    findings = evaluate_rules(diff, new_graph=new_g, old_graph=old_g)
    # The fixture removes Dog.fetch (referenced in test_models.py only on the
    # old side) and modifies Dog.speak. We expect at least one finding.
    assert findings
    # Modified-signature rule should fire for Dog.speak.
    assert any(
        f.rule_id == "modified-signature" and f.qualname.endswith("Dog.speak")
        for f in findings
    )


def test_load_rules_falls_back_to_defaults(tmp_path: Path) -> None:
    rules = load_rules(tmp_path / "missing.yml")
    assert rules == DEFAULT_RULES


def test_load_rules_parses_yaml(tmp_path: Path) -> None:
    yml = tmp_path / "rules.yml"
    yml.write_text(
        """
rules:
  - id: ban-internal-imports
    when: added_node
    severity: high
    message: "no new internal imports"
    match:
      kind: FUNCTION
      qualname_prefix: pkg.
""".strip()
    )
    rules = load_rules(yml)
    assert len(rules) == 1
    assert rules[0].id == "ban-internal-imports"
    assert rules[0].match.qualname_prefix == "pkg."


def test_evaluate_rules_with_custom_rule(
    graphs: tuple[nx.MultiDiGraph, nx.MultiDiGraph],
) -> None:
    old_g, new_g = graphs
    diff = diff_graphs(old_g, new_g)
    custom = [
        Rule(
            id="any-add",
            when="added_node",
            severity="med",
            message="added: {qualname}",
        )
    ]
    findings = evaluate_rules(
        diff, new_graph=new_g, old_graph=old_g, rules=custom
    )
    assert findings
    assert all(f.rule_id == "any-add" for f in findings)
