"""Untested-symbol detection."""
from __future__ import annotations

from dataclasses import dataclass

import networkx as nx

from codegraph.analysis._common import (
    _kind_str,
    in_protocol_class,
    in_test_module,
    is_excluded_path,
)
from codegraph.graph.schema import EdgeKind, NodeKind

_CANDIDATE_KINDS: frozenset[str] = frozenset(
    {NodeKind.FUNCTION.value, NodeKind.METHOD.value}
)


@dataclass
class UntestedNode:
    id: str
    name: str
    qualname: str
    kind: str
    file: str
    line_start: int
    incoming_calls: int


def find_untested(graph: nx.MultiDiGraph) -> list[UntestedNode]:
    """Functions/methods with no incoming CALLS edge from a test module.

    Skips functions that themselves live in a test module and skips dunder
    helpers (``__init__``, etc.) since users rarely test them directly.
    """
    out: list[UntestedNode] = []
    for nid, attrs in graph.nodes(data=True):
        kind = _kind_str(attrs.get("kind"))
        if kind not in _CANDIDATE_KINDS:
            continue
        name = str(attrs.get("name") or "")
        if name.startswith("__") and name.endswith("__"):
            continue
        if in_test_module(graph, nid):
            continue
        # Skip test fixtures and static frontend assets — same exclusion as
        # the dead-code analyzer.
        if is_excluded_path(str(attrs.get("file") or "")):
            continue
        # Skip methods defined inside a ``typing.Protocol`` class: Protocol
        # methods are structural type definitions, not runtime code, so
        # "untested" is meaningless for them.
        if kind == NodeKind.METHOD.value and in_protocol_class(graph, nid):
            continue
        incoming = 0
        from_test = 0
        for src, _dst, key in graph.in_edges(nid, keys=True):
            if key != EdgeKind.CALLS.value:
                continue
            incoming += 1
            if in_test_module(graph, src):
                from_test += 1
        if from_test > 0:
            continue
        out.append(
            UntestedNode(
                id=nid,
                name=name,
                qualname=str(attrs.get("qualname") or name),
                kind=kind,
                file=str(attrs.get("file") or ""),
                line_start=int(attrs.get("line_start") or 0),
                incoming_calls=incoming,
            )
        )
    out.sort(key=lambda u: (-u.incoming_calls, u.file, u.line_start))
    return out
