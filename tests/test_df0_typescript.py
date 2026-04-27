"""DF0 tests for TypeScript parser: function params + per-call-site args.

The kwargs split rule:
    A trailing object-literal argument is split into ``kwargs`` only when there
    is exactly one object-literal argument AND it is the last positional. Any
    other shape (multiple object literals, non-trailing object literal) keeps
    the object as a normal positional argument (simplified to "<expr>" since
    object literals are not in the simple-expression allow-list).
"""
from __future__ import annotations

from pathlib import Path

import pytest

from codegraph.graph.schema import Edge, EdgeKind, Node, NodeKind
from codegraph.parsers.typescript import TypeScriptExtractor

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "df0_typescript"


@pytest.fixture(scope="module")
def parsed() -> tuple[list[Node], list[Edge]]:
    extractor = TypeScriptExtractor()
    return extractor.parse_file(FIXTURE_DIR / "sample.ts", FIXTURE_DIR)


def _func(nodes: list[Node], name: str) -> Node:
    for n in nodes:
        if n.kind in (NodeKind.FUNCTION, NodeKind.METHOD) and n.name == name:
            return n
    raise AssertionError(f"function {name!r} not found")


def _calls_in(edges: list[Edge], target_suffix: str) -> list[Edge]:
    out = []
    for e in edges:
        if e.kind != EdgeKind.CALLS:
            continue
        tn = e.metadata.get("target_name", "")
        if tn == target_suffix or tn.endswith(target_suffix):
            out.append(e)
    return out


# ---------- function params / returns ----------


def test_plain_params_no_types(parsed: tuple[list[Node], list[Edge]]) -> None:
    nodes, _ = parsed
    f = _func(nodes, "plain")
    assert f.metadata["params"] == [
        {"name": "a", "type": None, "default": None},
        {"name": "b", "type": None, "default": None},
    ]
    assert f.metadata["returns"] is None


def test_typed_params_with_default_and_return(
    parsed: tuple[list[Node], list[Edge]],
) -> None:
    nodes, _ = parsed
    f = _func(nodes, "typed")
    assert f.metadata["params"] == [
        {"name": "a", "type": "number", "default": None},
        {"name": "b", "type": "string", "default": '"x"'},
    ]
    assert f.metadata["returns"] == "boolean"


def test_method_params_on_class(parsed: tuple[list[Node], list[Edge]]) -> None:
    nodes, _ = parsed
    m = _func(nodes, "m")
    assert m.kind == NodeKind.METHOD
    assert m.metadata["params"] == [
        {"name": "x", "type": "number", "default": None},
    ]
    assert m.metadata["returns"] == "void"


def test_arrow_function_captured_as_function(
    parsed: tuple[list[Node], list[Edge]],
) -> None:
    nodes, _ = parsed
    f = _func(nodes, "arrow")
    assert f.kind == NodeKind.FUNCTION
    assert f.metadata.get("arrow") is True
    assert f.metadata["params"] == [
        {"name": "a", "type": "T", "default": None},
    ]


def test_optional_param(parsed: tuple[list[Node], list[Edge]]) -> None:
    nodes, _ = parsed
    f = _func(nodes, "optional")
    # We choose to record optional params as {name: "a", type: "number"}; the
    # `?` marker is implicit (not present in default/name).
    assert f.metadata["params"] == [
        {"name": "a", "type": "number", "default": None},
    ]


def test_rest_param(parsed: tuple[list[Node], list[Edge]]) -> None:
    nodes, _ = parsed
    f = _func(nodes, "rest")
    assert f.metadata["params"] == [
        {"name": "...args", "type": "number[]", "default": None},
    ]


# ---------- call-site args / kwargs ----------


def test_plain_call_args(parsed: tuple[list[Node], list[Edge]]) -> None:
    _, edges = parsed
    calls = _calls_in(edges, "plain")
    assert calls, "expected a call to plain()"
    md = calls[0].metadata
    assert md["args"] == ["1", '"x"', "y"]
    assert md["kwargs"] == {}


def test_object_literal_as_kwargs(
    parsed: tuple[list[Node], list[Edge]],
) -> None:
    _, edges = parsed
    calls = _calls_in(edges, "fetch")
    assert calls, "expected a call to fetch()"
    md = calls[0].metadata
    assert md["args"] == ['"/x"']
    assert md["kwargs"] == {"method": '"POST"', "body": "data"}


def test_trailing_object_split_into_kwargs(
    parsed: tuple[list[Node], list[Edge]],
) -> None:
    _, edges = parsed
    calls = _calls_in(edges, "trailingObj")
    assert calls, "expected a call to trailingObj()"
    md = calls[0].metadata
    # Single trailing object literal -> split into kwargs (chosen rule).
    assert md["args"] == ["1"]
    assert md["kwargs"] == {"x": "2"}


def test_multiple_object_literals_not_split(
    parsed: tuple[list[Node], list[Edge]],
) -> None:
    _, edges = parsed
    calls = _calls_in(edges, "multiObj")
    assert calls, "expected a call to multiObj()"
    md = calls[0].metadata
    # Multiple object args -> not split; each becomes a simplified expr.
    assert md["args"] == ["<expr>", "<expr>"]
    assert md["kwargs"] == {}


def test_complex_args_simplified(
    parsed: tuple[list[Node], list[Edge]],
) -> None:
    _, edges = parsed
    calls = _calls_in(edges, "complex")
    assert calls, "expected a call to complex()"
    md = calls[0].metadata
    # `a + b` (binary_expression) and `foo.bar()` (call_expression) both
    # collapse to "<expr>".
    assert md["args"] == ["<expr>", "<expr>"]


def test_member_arg_captured_as_text(
    parsed: tuple[list[Node], list[Edge]],
) -> None:
    _, edges = parsed
    calls = _calls_in(edges, "member")
    assert calls
    md = calls[0].metadata
    assert md["args"] == ["obj.x.y"]


def test_spread_arg(parsed: tuple[list[Node], list[Edge]]) -> None:
    _, edges = parsed
    calls = _calls_in(edges, "spread")
    assert calls
    md = calls[0].metadata
    assert md["args"] == ["*args"]
    assert md["kwargs"] == {}


def test_jsx_function_captures_params() -> None:
    extractor = TypeScriptExtractor()
    nodes, _ = extractor.parse_file(
        FIXTURE_DIR / "jsx_sample.tsx", FIXTURE_DIR
    )
    f = _func(nodes, "Greet")
    assert f.metadata["params"] == [
        {"name": "name", "type": "string", "default": None},
    ]
    assert f.metadata["returns"] == "JSX.Element"
