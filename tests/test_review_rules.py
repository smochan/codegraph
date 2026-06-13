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


def _add_fn(
    g: nx.MultiDiGraph,
    qn: str,
    *,
    file: str = "pkg/foo.py",
    line: int = 1,
) -> None:
    g.add_node(
        f"node::{qn}",
        qualname=qn,
        kind="FUNCTION",
        file=file,
        line_start=line,
        signature=f"{qn.rsplit('.', 1)[-1]}()",
    )


def test_removed_referenced_skips_moved_symbol() -> None:
    """Regression test: a symbol moved to another module (removed at one
    qualname, added at another with the same terminal name and kind) must
    not fire ``removed-referenced``. PR #73 flagged esc/pyvisHref/
    mermaidThemeVars as critical after they moved from app.js to
    ui/helpers.js with every caller updated."""
    old_g: nx.MultiDiGraph = nx.MultiDiGraph()
    new_g: nx.MultiDiGraph = nx.MultiDiGraph()
    _add_fn(old_g, "pkg.app.esc", file="app.js")
    _add_fn(old_g, "pkg.app.render", file="app.js", line=10)
    old_g.add_edge("node::pkg.app.render", "node::pkg.app.esc", key="CALLS", kind="CALLS")
    # esc moved to helpers; caller render survives.
    _add_fn(new_g, "pkg.ui.helpers.esc", file="ui/helpers.js")
    _add_fn(new_g, "pkg.app.render", file="app.js", line=10)
    diff = diff_graphs(old_g, new_g)
    findings = evaluate_rules(diff, new_graph=new_g, old_graph=old_g)
    assert not [f for f in findings if f.rule_id == "removed-referenced"], (
        "moved symbol must not be reported as removed-referenced"
    )


def test_removed_referenced_still_fires_for_real_removal() -> None:
    """Control: genuinely deleting a symbol that callers still reference
    keeps firing critical."""
    old_g: nx.MultiDiGraph = nx.MultiDiGraph()
    new_g: nx.MultiDiGraph = nx.MultiDiGraph()
    _add_fn(old_g, "pkg.app.esc", file="app.js")
    _add_fn(old_g, "pkg.app.render", file="app.js", line=10)
    old_g.add_edge("node::pkg.app.render", "node::pkg.app.esc", key="CALLS", kind="CALLS")
    _add_fn(new_g, "pkg.app.render", file="app.js", line=10)
    diff = diff_graphs(old_g, new_g)
    findings = evaluate_rules(diff, new_graph=new_g, old_graph=old_g)
    assert [f for f in findings if f.rule_id == "removed-referenced"]


def test_new_untested_hotspot_skips_moved_symbol() -> None:
    """Regression test: a symbol that MOVED modules is not NEW code — its
    test-coverage state predates the PR. PR #73 flagged formatQn as a new
    untested hotspot after it moved from app.js to ui/helpers.js."""
    old_g: nx.MultiDiGraph = nx.MultiDiGraph()
    new_g: nx.MultiDiGraph = nx.MultiDiGraph()
    _add_fn(old_g, "pkg.app.formatQn", file="app.js")
    _add_fn(new_g, "pkg.ui.helpers.formatQn", file="ui/helpers.js")
    # Give the moved symbol >= 5 non-test callers in the new graph.
    for i in range(5):
        caller = f"pkg.views.v{i}.render"
        _add_fn(old_g, caller, file=f"views/v{i}.js")
        _add_fn(new_g, caller, file=f"views/v{i}.js")
        new_g.add_edge(
            f"node::{caller}", "node::pkg.ui.helpers.formatQn",
            key="CALLS", kind="CALLS",
        )
    diff = diff_graphs(old_g, new_g)
    findings = evaluate_rules(diff, new_graph=new_g, old_graph=old_g)
    assert not [f for f in findings if f.rule_id == "new-untested-hotspot"], (
        "moved symbol must not be reported as a new untested hotspot"
    )


def test_new_untested_hotspot_still_fires_for_genuinely_new() -> None:
    """Control: a genuinely new high-fan-in untested function still fires."""
    old_g: nx.MultiDiGraph = nx.MultiDiGraph()
    new_g: nx.MultiDiGraph = nx.MultiDiGraph()
    _add_fn(new_g, "pkg.core.hotNew", file="core.py")
    for i in range(5):
        caller = f"pkg.views.v{i}.render"
        _add_fn(old_g, caller, file=f"views/v{i}.py")
        _add_fn(new_g, caller, file=f"views/v{i}.py")
        new_g.add_edge(
            f"node::{caller}", "node::pkg.core.hotNew",
            key="CALLS", kind="CALLS",
        )
    diff = diff_graphs(old_g, new_g)
    findings = evaluate_rules(diff, new_graph=new_g, old_graph=old_g)
    assert [f for f in findings if f.rule_id == "new-untested-hotspot"]


def test_new_dead_code_skips_moved_symbol() -> None:
    """A moved symbol with zero callers was already dead before the PR;
    new-dead-code only reports genuinely new unreachable code."""
    old_g: nx.MultiDiGraph = nx.MultiDiGraph()
    new_g: nx.MultiDiGraph = nx.MultiDiGraph()
    _add_fn(old_g, "pkg.app.orphan", file="app.js")
    _add_fn(new_g, "pkg.ui.helpers.orphan", file="ui/helpers.js")
    diff = diff_graphs(old_g, new_g)
    findings = evaluate_rules(diff, new_graph=new_g, old_graph=old_g)
    assert not [f for f in findings if f.rule_id == "new-dead-code"]
