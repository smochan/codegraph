"""Dead code detection: definitions with no incoming references."""
from __future__ import annotations

from dataclasses import dataclass

import networkx as nx

from codegraph.analysis._common import (
    REFERENCE_EDGE_KINDS,
    _kind_str,
    in_test_module,
    is_excluded_path,
)
from codegraph.graph.schema import EdgeKind, NodeKind

_CANDIDATE_KINDS: frozenset[str] = frozenset(
    {NodeKind.FUNCTION.value, NodeKind.METHOD.value, NodeKind.CLASS.value}
)
_ENTRYPOINT_NAMES: frozenset[str] = frozenset({"main", "__main__"})

_PROPERTY_DECORATORS: tuple[str, ...] = (
    "@property", "@cached_property", "functools.cached_property",
)


def _has_property_decorator(metadata: dict[str, object]) -> bool:
    decorators = metadata.get("decorators") or []
    if not isinstance(decorators, list):
        return False
    for raw in decorators:
        text = str(raw).strip()
        for marker in _PROPERTY_DECORATORS:
            if marker in text:
                return True
    return False


def _class_has_inherits(graph: nx.MultiDiGraph, class_id: str) -> bool:
    return any(
        key == EdgeKind.INHERITS.value
        for _src, _dst, key in graph.out_edges(class_id, keys=True)
    )


def _is_polymorphic_override(graph: nx.MultiDiGraph, method_id: str) -> bool:
    """True if the method's owning class inherits from another class.

    Such methods are likely overrides invoked via base-class dispatch and
    have no static incoming CALL edge.
    """
    for _src, dst, key in graph.out_edges(method_id, keys=True):
        if key != EdgeKind.DEFINED_IN.value:
            continue
        attrs = graph.nodes.get(dst) or {}
        if (
            _kind_str(attrs.get("kind")) == NodeKind.CLASS.value
            and _class_has_inherits(graph, dst)
        ):
            return True
    return False


@dataclass
class DeadNode:
    id: str
    name: str
    qualname: str
    kind: str
    file: str
    line_start: int
    reason: str = "no incoming references"


def _is_dunder(name: str) -> bool:
    return name.startswith("__") and name.endswith("__")


def _is_test_function(name: str) -> bool:
    return name.startswith("test_") or name.startswith("test")


def find_dead_code(
    graph: nx.MultiDiGraph,
    *,
    include_tests: bool = False,
) -> list[DeadNode]:
    """Return definitions with no incoming reference edges.

    Excludes (by default):
      * Nodes living in test modules
      * dunder methods and ``main`` entrypoints
      * Names starting with ``test_`` (treated as test functions)

    A function/class is "dead" if no other node CALLS / INHERITS / IMPLEMENTS
    / IMPORTS it. Methods of an inherited class are still flagged, but a
    method with an INHERITS-edge incoming counts as referenced.
    """
    dead: list[DeadNode] = []
    for nid, attrs in graph.nodes(data=True):
        kind = _kind_str(attrs.get("kind"))
        if kind not in _CANDIDATE_KINDS:
            continue
        name = str(attrs.get("name") or "")
        if name in _ENTRYPOINT_NAMES:
            continue
        if _is_dunder(name):
            continue
        if _is_test_function(name):
            continue
        if not include_tests and in_test_module(graph, nid):
            continue
        # Decorator/entry-point-aware skip: framework hooks (Typer commands,
        # FastAPI routes, pytest fixtures, abstract methods, Celery tasks,
        # etc.) are invoked dynamically and have no static incoming edge.
        # The Python parser tags them with metadata["entry_point"] = True.
        metadata = attrs.get("metadata") or {}
        if metadata.get("entry_point"):
            continue
        # @property / @cached_property are accessed as attributes, not calls.
        if _has_property_decorator(metadata):
            continue
        # Generated/static frontend assets and test fixtures don't have
        # traceable call graphs — exclude them from dead-code detection.
        if is_excluded_path(str(attrs.get("file") or "")):
            continue
        # Polymorphic overrides on classes that inherit have no static
        # incoming CALL edge (dispatch is via the base class).
        if kind == NodeKind.METHOD.value and _is_polymorphic_override(graph, nid):
            continue

        has_incoming_ref = False
        for _src, _dst, key in graph.in_edges(nid, keys=True):
            if key in REFERENCE_EDGE_KINDS:
                has_incoming_ref = True
                break
        if has_incoming_ref:
            continue

        dead.append(
            DeadNode(
                id=nid,
                name=name,
                qualname=str(attrs.get("qualname") or name),
                kind=kind,
                file=str(attrs.get("file") or ""),
                line_start=int(attrs.get("line_start") or 0),
            )
        )
    dead.sort(key=lambda d: (d.file, d.line_start, d.qualname))
    return dead
