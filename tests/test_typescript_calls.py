"""Tests for TypeScriptExtractor._collect_calls — direct unit-level checks."""
from __future__ import annotations

from codegraph.graph.schema import Edge, EdgeKind
from codegraph.parsers.base import load_parser
from codegraph.parsers.typescript import TypeScriptExtractor


def _collect_for_source(src: str) -> list[Edge]:
    extractor = TypeScriptExtractor()
    parser = load_parser("typescript")
    tree = parser.parse(src.encode("utf-8"))
    edges: list[Edge] = []
    extractor._collect_calls(
        tree.root_node, "x.ts", "scope-id", src.encode("utf-8"), edges
    )
    return edges


def test_collect_calls_simple_call_expression() -> None:
    edges = _collect_for_source("foo();\n")
    calls = [e for e in edges if e.kind == EdgeKind.CALLS]
    assert len(calls) == 1
    assert calls[0].src == "scope-id"
    assert calls[0].dst.startswith("unresolved::")
    assert "foo" in calls[0].dst


def test_collect_calls_member_access() -> None:
    edges = _collect_for_source("obj.method(1, 2);\n")
    calls = [e for e in edges if e.kind == EdgeKind.CALLS]
    assert len(calls) == 1
    target = calls[0].metadata.get("target_name", "")
    assert "obj.method" in target


def test_collect_calls_multiple_distinct_calls() -> None:
    src = "foo();\nbar();\nbaz.qux();\n"
    edges = _collect_for_source(src)
    calls = [e for e in edges if e.kind == EdgeKind.CALLS]
    assert len(calls) == 3
    targets = sorted(e.metadata.get("target_name", "") for e in calls)
    assert any("foo" in t for t in targets)
    assert any("bar" in t for t in targets)
    assert any("baz.qux" in t for t in targets)


def test_collect_calls_no_calls_in_empty_block() -> None:
    edges = _collect_for_source("const x = 1;\n")
    calls = [e for e in edges if e.kind == EdgeKind.CALLS]
    assert calls == []


def test_collect_calls_records_line_numbers() -> None:
    src = "\n\nfoo();\n"
    edges = _collect_for_source(src)
    calls = [e for e in edges if e.kind == EdgeKind.CALLS]
    assert len(calls) == 1
    assert calls[0].line == 3
    assert calls[0].file == "x.ts"


def test_collect_calls_nested_call_inside_arg() -> None:
    edges = _collect_for_source("outer(inner());\n")
    calls = [e for e in edges if e.kind == EdgeKind.CALLS]
    targets = [e.metadata.get("target_name", "") for e in calls]
    assert any("outer" in t for t in targets)
    assert any("inner" in t for t in targets)
