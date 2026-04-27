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


def _add_class(
    g: nx.MultiDiGraph,
    cls_id: str,
    name: str,
    qualname: str,
    file_path: str,
    *,
    inherits: list[str] | None = None,
) -> None:
    g.add_node(
        cls_id,
        kind=NodeKind.CLASS.value,
        name=name,
        qualname=qualname,
        file=file_path,
        line_start=1,
        language="python",
        metadata={},
    )
    for parent_name in inherits or []:
        unresolved_id = f"unresolved::{parent_name}"
        if unresolved_id not in g:
            g.add_node(
                unresolved_id,
                kind="UNRESOLVED",
                name=parent_name,
                qualname=parent_name,
                file="",
                line_start=0,
                language="python",
                metadata={},
            )
        g.add_edge(
            cls_id,
            unresolved_id,
            key=EdgeKind.INHERITS.value,
            kind=EdgeKind.INHERITS.value,
            metadata={"target_name": parent_name},
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


# ----- Protocol skip ----------------------------------------------------


def test_dead_code_skips_protocol_class() -> None:
    g: nx.MultiDiGraph = nx.MultiDiGraph()
    _add_module(g, "mod::p", "src/pkg/proto.py")
    _add_class(
        g,
        "cls::Encoder",
        "Encoder",
        "pkg.proto.Encoder",
        "src/pkg/proto.py",
        inherits=["Protocol"],
    )
    _add_defined_in(g, "cls::Encoder", "mod::p")

    dead_qualnames = {d.qualname for d in find_dead_code(g)}
    assert "pkg.proto.Encoder" not in dead_qualnames


def test_dead_code_skips_methods_inside_protocol_class() -> None:
    g: nx.MultiDiGraph = nx.MultiDiGraph()
    _add_module(g, "mod::p", "src/pkg/proto.py")
    _add_class(
        g,
        "cls::Encoder",
        "Encoder",
        "pkg.proto.Encoder",
        "src/pkg/proto.py",
        inherits=["typing.Protocol"],
    )
    _add_defined_in(g, "cls::Encoder", "mod::p")
    _add_function(
        g,
        "m::encode",
        "encode",
        "pkg.proto.Encoder.encode",
        "src/pkg/proto.py",
        kind=NodeKind.METHOD.value,
    )
    _add_defined_in(g, "m::encode", "cls::Encoder")

    dead_qualnames = {d.qualname for d in find_dead_code(g)}
    assert "pkg.proto.Encoder.encode" not in dead_qualnames


def test_untested_skips_methods_inside_protocol_class() -> None:
    g: nx.MultiDiGraph = nx.MultiDiGraph()
    _add_module(g, "mod::p", "src/pkg/proto.py")
    _add_class(
        g,
        "cls::Encoder",
        "Encoder",
        "pkg.proto.Encoder",
        "src/pkg/proto.py",
        inherits=["Protocol"],
    )
    _add_defined_in(g, "cls::Encoder", "mod::p")
    _add_function(
        g,
        "m::encode",
        "encode",
        "pkg.proto.Encoder.encode",
        "src/pkg/proto.py",
        kind=NodeKind.METHOD.value,
    )
    _add_defined_in(g, "m::encode", "cls::Encoder")

    untested_qualnames = {u.qualname for u in find_untested(g)}
    assert "pkg.proto.Encoder.encode" not in untested_qualnames


def test_dead_code_still_flags_non_protocol_class() -> None:
    g: nx.MultiDiGraph = nx.MultiDiGraph()
    _add_module(g, "mod::s", "src/pkg/svc.py")
    _add_class(
        g,
        "cls::Orphan",
        "Orphan",
        "pkg.svc.Orphan",
        "src/pkg/svc.py",
    )
    _add_defined_in(g, "cls::Orphan", "mod::s")

    dead_qualnames = {d.qualname for d in find_dead_code(g)}
    assert "pkg.svc.Orphan" in dead_qualnames


def test_dead_code_still_flags_non_protocol_class_method() -> None:
    g: nx.MultiDiGraph = nx.MultiDiGraph()
    _add_module(g, "mod::s", "src/pkg/svc.py")
    _add_class(
        g,
        "cls::Plain",
        "Plain",
        "pkg.svc.Plain",
        "src/pkg/svc.py",
    )
    _add_defined_in(g, "cls::Plain", "mod::s")
    # Give the class an incoming CALL edge to keep it alive (so we are
    # specifically asserting the method gets flagged).
    _add_function(
        g,
        "fn::caller",
        "caller",
        "pkg.svc.caller",
        "src/pkg/svc.py",
    )
    _add_defined_in(g, "fn::caller", "mod::s")
    g.add_edge(
        "fn::caller",
        "cls::Plain",
        key=EdgeKind.CALLS.value,
        kind=EdgeKind.CALLS.value,
        metadata={},
    )
    _add_function(
        g,
        "m::do_work",
        "do_work",
        "pkg.svc.Plain.do_work",
        "src/pkg/svc.py",
        kind=NodeKind.METHOD.value,
    )
    _add_defined_in(g, "m::do_work", "cls::Plain")

    dead_qualnames = {d.qualname for d in find_dead_code(g)}
    assert "pkg.svc.Plain.do_work" in dead_qualnames


def test_analyzers_handle_missing_inherits_edges() -> None:
    """A class with no INHERITS out-edges should not blow up either analyzer."""
    g: nx.MultiDiGraph = nx.MultiDiGraph()
    _add_module(g, "mod::s", "src/pkg/svc.py")
    _add_class(
        g,
        "cls::Bare",
        "Bare",
        "pkg.svc.Bare",
        "src/pkg/svc.py",
    )
    _add_defined_in(g, "cls::Bare", "mod::s")
    _add_function(
        g,
        "m::tick",
        "tick",
        "pkg.svc.Bare.tick",
        "src/pkg/svc.py",
        kind=NodeKind.METHOD.value,
    )
    _add_defined_in(g, "m::tick", "cls::Bare")

    # Should not raise.
    dead = find_dead_code(g)
    untested = find_untested(g)
    assert any(d.qualname == "pkg.svc.Bare" for d in dead)
    assert any(u.qualname == "pkg.svc.Bare.tick" for u in untested)
