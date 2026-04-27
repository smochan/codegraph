"""Direct unit tests for kind_str helpers in viz._style and review.differ."""
from __future__ import annotations

from enum import Enum

from codegraph.graph.schema import EdgeKind, NodeKind
from codegraph.review import differ
from codegraph.viz._style import kind_str


class _DummyEnum(Enum):
    FOO = "FOO_VAL"


def test_kind_str_with_enum_returns_value() -> None:
    assert kind_str(NodeKind.FUNCTION) == "FUNCTION"


def test_kind_str_with_string_returns_string() -> None:
    assert kind_str("CLASS") == "CLASS"


def test_kind_str_with_none_returns_empty_string() -> None:
    assert kind_str(None) == ""


def test_kind_str_with_arbitrary_enum_returns_value() -> None:
    assert kind_str(_DummyEnum.FOO) == "FOO_VAL"


def test_kind_str_with_int_returns_str() -> None:
    assert kind_str(42) == "42"


def test_kind_str_with_empty_string() -> None:
    assert kind_str("") == ""


def test_differ_kind_str_with_edge_enum() -> None:
    assert differ._kind_str(EdgeKind.CALLS) == "CALLS"


def test_differ_kind_str_with_string_passthrough() -> None:
    assert differ._kind_str("DEFINED_IN") == "DEFINED_IN"


def test_differ_kind_str_with_none() -> None:
    assert differ._kind_str(None) == ""


def test_differ_kind_str_with_object_without_value_attr() -> None:
    assert differ._kind_str(123) == "123"
