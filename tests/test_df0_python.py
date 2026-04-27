"""DF0: Python parameter capture + per-call-site argument capture.

Each test writes a small fixture into a temporary directory and runs the
``PythonExtractor`` on it. We assert directly against ``Node.metadata`` /
``Edge.metadata`` to lock in the V2/V3/V4/V5 contract.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from codegraph.graph.schema import Edge, EdgeKind, Node, NodeKind
from codegraph.parsers.python import PythonExtractor


def _run_extractor_on_source(
    tmp_path: Path, src: str, filename: str = "sample.py"
) -> tuple[list[Node], list[Edge]]:
    target = tmp_path / filename
    target.write_text(src)
    return PythonExtractor().parse_file(target, tmp_path)


def _find_func(nodes: list[Node], name: str) -> Node:
    return next(n for n in nodes if n.name == name)


def _calls_edges(edges: list[Edge]) -> list[Edge]:
    return [e for e in edges if e.kind == EdgeKind.CALLS]


def _params_of(nodes: list[Node], name: str) -> list[dict[str, Any]]:
    return _find_func(nodes, name).metadata["params"]  # type: ignore[no-any-return]


# --- Function signature capture ----------------------------------------


def test_plain_function_positional_params(tmp_path: Path) -> None:
    nodes, _ = _run_extractor_on_source(tmp_path, "def f(a, b):\n    pass\n")
    f = _find_func(nodes, "f")
    assert f.metadata["params"] == [
        {"name": "a", "type": None, "default": None},
        {"name": "b", "type": None, "default": None},
    ]
    assert f.metadata["returns"] is None


def test_typed_params_and_return(tmp_path: Path) -> None:
    src = 'def f(a: int, b: str = "x") -> bool:\n    pass\n'
    nodes, _ = _run_extractor_on_source(tmp_path, src)
    f = _find_func(nodes, "f")
    assert f.metadata["params"] == [
        {"name": "a", "type": "int", "default": None},
        {"name": "b", "type": "str", "default": '"x"'},
    ]
    assert f.metadata["returns"] == "bool"


def test_method_skips_self(tmp_path: Path) -> None:
    src = "class C:\n    def m(self, x):\n        pass\n"
    nodes, _ = _run_extractor_on_source(tmp_path, src)
    m = _find_func(nodes, "m")
    assert m.kind == NodeKind.METHOD
    assert m.metadata["params"] == [
        {"name": "x", "type": None, "default": None},
    ]


def test_variadic_params(tmp_path: Path) -> None:
    src = "def f(*args, **kwargs):\n    pass\n"
    nodes, _ = _run_extractor_on_source(tmp_path, src)
    params = _params_of(nodes, "f")
    names = [p["name"] for p in params]
    assert "*args" in names
    assert "**kwargs" in names


def test_classmethod_skips_cls(tmp_path: Path) -> None:
    src = (
        "class C:\n"
        "    @classmethod\n"
        "    def m(cls, x):\n"
        "        pass\n"
    )
    nodes, _ = _run_extractor_on_source(tmp_path, src)
    m = _find_func(nodes, "m")
    assert m.kind == NodeKind.METHOD
    assert m.metadata["params"] == [
        {"name": "x", "type": None, "default": None},
    ]


# --- Call-site argument capture ----------------------------------------


def test_call_positional_args(tmp_path: Path) -> None:
    src = 'def caller():\n    f(1, "x", y)\n'
    _, edges = _run_extractor_on_source(tmp_path, src)
    call = next(e for e in _calls_edges(edges) if e.metadata.get("target_name") == "f")
    assert call.metadata["args"] == ["1", '"x"', "y"]
    assert call.metadata["kwargs"] == {}


def test_call_keyword_args(tmp_path: Path) -> None:
    src = 'def caller():\n    f(name="bob", age=30)\n'
    _, edges = _run_extractor_on_source(tmp_path, src)
    call = next(e for e in _calls_edges(edges) if e.metadata.get("target_name") == "f")
    assert call.metadata["args"] == []
    assert call.metadata["kwargs"] == {"name": '"bob"', "age": "30"}


def test_call_mixed_positional_and_keyword(tmp_path: Path) -> None:
    src = 'def caller():\n    f(1, name="x")\n'
    _, edges = _run_extractor_on_source(tmp_path, src)
    call = next(e for e in _calls_edges(edges) if e.metadata.get("target_name") == "f")
    assert call.metadata["args"] == ["1"]
    assert call.metadata["kwargs"] == {"name": '"x"'}


def test_call_complex_expression_simplified(tmp_path: Path) -> None:
    src = "def caller():\n    f(1 + 2, foo.bar.baz())\n"
    _, edges = _run_extractor_on_source(tmp_path, src)
    call = next(e for e in _calls_edges(edges) if e.metadata.get("target_name") == "f")
    # ``1 + 2`` is a binary_operator (not simple); ``foo.bar.baz()`` is a
    # call (not simple) — both collapse to "<expr>".
    assert call.metadata["args"] == ["<expr>", "<expr>"]


def test_call_attribute_capture(tmp_path: Path) -> None:
    src = "def caller():\n    f(self.x, obj.attr)\n"
    _, edges = _run_extractor_on_source(tmp_path, src)
    call = next(e for e in _calls_edges(edges) if e.metadata.get("target_name") == "f")
    assert call.metadata["args"] == ["self.x", "obj.attr"]


def test_call_subscript_capture(tmp_path: Path) -> None:
    src = "def caller():\n    f(items[0])\n"
    _, edges = _run_extractor_on_source(tmp_path, src)
    call = next(e for e in _calls_edges(edges) if e.metadata.get("target_name") == "f")
    assert call.metadata["args"] == ["items[0]"]


def test_call_spread_args_and_kwargs(tmp_path: Path) -> None:
    src = "def caller():\n    f(*more, **opts)\n"
    _, edges = _run_extractor_on_source(tmp_path, src)
    call = next(e for e in _calls_edges(edges) if e.metadata.get("target_name") == "f")
    assert call.metadata["args"] == ["*more"]
    assert call.metadata["kwargs"] == {"**": "opts"}


# --- Bonus coverage ----------------------------------------------------


def test_module_level_call_carries_args(tmp_path: Path) -> None:
    """Top-level (module-scope) calls also get args/kwargs metadata."""
    _, edges = _run_extractor_on_source(tmp_path, 'f(1, name="x")\n')
    call = next(e for e in _calls_edges(edges) if e.metadata.get("target_name") == "f")
    assert call.metadata["args"] == ["1"]
    assert call.metadata["kwargs"] == {"name": '"x"'}


def test_no_args_call(tmp_path: Path) -> None:
    _, edges = _run_extractor_on_source(tmp_path, "def caller():\n    f()\n")
    call = next(e for e in _calls_edges(edges) if e.metadata.get("target_name") == "f")
    assert call.metadata["args"] == []
    assert call.metadata["kwargs"] == {}


@pytest.mark.parametrize(
    "literal,expected",
    [
        ("True", "True"),
        ("False", "False"),
        ("None", "None"),
        ("3.14", "3.14"),
    ],
)
def test_call_literal_kinds_captured(
    tmp_path: Path, literal: str, expected: str
) -> None:
    src = f"def caller():\n    f({literal})\n"
    _, edges = _run_extractor_on_source(tmp_path, src)
    call = next(e for e in _calls_edges(edges) if e.metadata.get("target_name") == "f")
    assert call.metadata["args"] == [expected]
