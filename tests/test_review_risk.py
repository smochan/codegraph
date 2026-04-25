"""Tests for codegraph.review.risk."""
from __future__ import annotations

import networkx as nx

from codegraph.graph.schema import EdgeKind
from codegraph.review.differ import NodeChange
from codegraph.review.risk import score_change


def _make_graph(
    *,
    qualname: str,
    file: str,
    callers: int = 0,
    extra_qualname: str | None = None,
) -> nx.MultiDiGraph:
    g: nx.MultiDiGraph = nx.MultiDiGraph()
    g.add_node(
        "target",
        qualname=qualname,
        kind="FUNCTION",
        file=file,
        line_start=1,
        line_end=10,
        signature=f"{qualname.rsplit('.', 1)[-1]}()",
    )
    for i in range(callers):
        cid = f"c{i}"
        g.add_node(
            cid,
            qualname=f"caller{i}",
            kind="FUNCTION",
            file=f"caller{i}.py",
            line_start=1,
            line_end=2,
            signature=f"caller{i}()",
        )
        g.add_edge(cid, "target", key=EdgeKind.CALLS.value, kind="CALLS")
    if extra_qualname:
        g.add_node(
            "extra",
            qualname=extra_qualname,
            kind="FUNCTION",
            file="extra.py",
            line_start=1,
            line_end=2,
            signature=f"{extra_qualname}()",
        )
    return g


def test_high_fan_in_scores_blast_radius() -> None:
    new_g = _make_graph(qualname="pkg.popular", file="pkg.py", callers=15)
    old_g = _make_graph(qualname="pkg.popular", file="pkg.py", callers=15)
    change = NodeChange(
        qualname="pkg.popular", kind="FUNCTION", file="pkg.py",
        line_start=1, signature="popular()", change_kind="modified",
    )
    risk = score_change(change, new_graph=new_g, old_graph=old_g)
    assert risk.score >= 40
    assert any("blast radius" in r for r in risk.reasons)


def test_removed_referenced_high_score() -> None:
    old_g: nx.MultiDiGraph = nx.MultiDiGraph()
    old_g.add_node(
        "victim", qualname="pkg.victim", kind="FUNCTION", file="pkg.py",
        line_start=1, line_end=2, signature="victim()",
    )
    old_g.add_node(
        "user", qualname="pkg.user", kind="FUNCTION", file="pkg.py",
        line_start=4, line_end=6, signature="user()",
    )
    old_g.add_edge("user", "victim", key=EdgeKind.CALLS.value, kind="CALLS")

    new_g: nx.MultiDiGraph = nx.MultiDiGraph()
    new_g.add_node(
        "user", qualname="pkg.user", kind="FUNCTION", file="pkg.py",
        line_start=4, line_end=6, signature="user()",
    )

    change = NodeChange(
        qualname="pkg.victim", kind="FUNCTION", file="pkg.py",
        line_start=1, signature="victim()", change_kind="removed",
    )
    risk = score_change(change, new_graph=new_g, old_graph=old_g)
    assert risk.score >= 50
    assert any("still referenced" in r for r in risk.reasons)


def test_signature_change_scores_modified() -> None:
    new_g = _make_graph(qualname="pkg.f", file="pkg.py")
    old_g = _make_graph(qualname="pkg.f", file="pkg.py")
    change = NodeChange(
        qualname="pkg.f", kind="FUNCTION", file="pkg.py",
        line_start=1, signature="f(a, b)", change_kind="modified",
        details={"signature": {"old": "f(a)", "new": "f(a, b)"}},
    )
    risk = score_change(change, new_graph=new_g, old_graph=old_g)
    assert risk.score >= 20
    assert any("signature change" in r for r in risk.reasons)


def test_added_unreachable_private_dead_code() -> None:
    new_g = _make_graph(qualname="pkg._helper", file="pkg.py", callers=0)
    old_g: nx.MultiDiGraph = nx.MultiDiGraph()
    change = NodeChange(
        qualname="pkg._helper", kind="FUNCTION", file="pkg.py",
        line_start=1, signature="_helper()", change_kind="added",
    )
    risk = score_change(change, new_graph=new_g, old_graph=old_g)
    assert any("unreachable" in r for r in risk.reasons)


def test_low_score_for_trivial_change() -> None:
    new_g = _make_graph(qualname="pkg.public_api", file="pkg.py", callers=1)
    old_g = _make_graph(qualname="pkg.public_api", file="pkg.py", callers=1)
    change = NodeChange(
        qualname="pkg.public_api", kind="FUNCTION", file="pkg.py",
        line_start=1, signature="public_api()", change_kind="added",
    )
    risk = score_change(change, new_graph=new_g, old_graph=old_g)
    assert risk.level in ("low", "med")
