"""Direct unit tests for roles helper functions (_set_role, _decorators)."""
from __future__ import annotations

import networkx as nx

from codegraph.analysis.roles import (
    COMPONENT,
    HANDLER,
    REPO,
    SERVICE,
    _decorators,
    _set_role,
)


def test_decorators_returns_string_list() -> None:
    attrs = {"metadata": {"decorators": ["@app.get('/')", "@cached"]}}
    assert _decorators(attrs) == ["@app.get('/')", "@cached"]


def test_decorators_handles_missing_metadata() -> None:
    assert _decorators({}) == []


def test_decorators_handles_none_metadata() -> None:
    assert _decorators({"metadata": None}) == []


def test_decorators_handles_non_dict_metadata() -> None:
    assert _decorators({"metadata": "not a dict"}) == []


def test_decorators_handles_non_list_decorators() -> None:
    assert _decorators({"metadata": {"decorators": "x"}}) == []


def test_decorators_coerces_items_to_str() -> None:
    attrs = {"metadata": {"decorators": [1, 2, "three"]}}
    assert _decorators(attrs) == ["1", "2", "three"]


def test_set_role_assigns_when_no_existing_role() -> None:
    g = nx.MultiDiGraph()
    g.add_node("n1", metadata={})
    assert _set_role(g, "n1", SERVICE) is True
    assert g.nodes["n1"]["metadata"]["role"] == SERVICE


def test_set_role_creates_metadata_dict_when_missing() -> None:
    g = nx.MultiDiGraph()
    g.add_node("n1")
    assert _set_role(g, "n1", REPO) is True
    assert g.nodes["n1"]["metadata"]["role"] == REPO


def test_set_role_replaces_metadata_when_not_dict() -> None:
    g = nx.MultiDiGraph()
    g.add_node("n1", metadata="bogus")
    assert _set_role(g, "n1", REPO) is True
    assert g.nodes["n1"]["metadata"] == {"role": REPO}


def test_set_role_respects_priority_higher_wins() -> None:
    g = nx.MultiDiGraph()
    g.add_node("n1", metadata={"role": SERVICE})
    # HANDLER has higher priority than SERVICE
    assert _set_role(g, "n1", HANDLER) is True
    assert g.nodes["n1"]["metadata"]["role"] == HANDLER


def test_set_role_rejects_lower_priority() -> None:
    g = nx.MultiDiGraph()
    g.add_node("n1", metadata={"role": HANDLER})
    assert _set_role(g, "n1", SERVICE) is False
    assert g.nodes["n1"]["metadata"]["role"] == HANDLER


def test_set_role_rejects_equal_priority() -> None:
    g = nx.MultiDiGraph()
    g.add_node("n1", metadata={"role": COMPONENT})
    assert _set_role(g, "n1", COMPONENT) is False


def test_set_role_returns_false_for_missing_node() -> None:
    g = nx.MultiDiGraph()
    assert _set_role(g, "ghost", SERVICE) is False
