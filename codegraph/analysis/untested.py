"""Untested-symbol detection."""
from __future__ import annotations

from dataclasses import dataclass, field

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
    hotspot_score: int = field(default=0)
    blast_radius_size: int = field(default=0)
    blast_files: int = field(default=0)


def _compute_hotspot_score(graph: nx.MultiDiGraph, nid: str) -> int:
    """Compute hotspot score for a node: fan_in*2 + fan_out + loc//50.

    Uses the same formula as :func:`codegraph.analysis.hotspots.Hotspot.score`.
    """
    attrs = graph.nodes.get(nid) or {}
    fan_in = 0
    fan_out = 0
    for _src, _dst, key in graph.in_edges(nid, keys=True):
        if key == EdgeKind.CALLS.value:
            fan_in += 1
    for _src, _dst, key in graph.out_edges(nid, keys=True):
        if key == EdgeKind.CALLS.value:
            fan_out += 1
    line_start = int(attrs.get("line_start") or 0)
    line_end = int(attrs.get("line_end") or 0)
    loc = max(0, line_end - line_start + 1) if line_end else 0
    return fan_in * 2 + fan_out + loc // 50


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


def rank_untested(
    graph: nx.MultiDiGraph,
    *,
    blast_depth: int = 3,
    top: int | None = None,
) -> list[UntestedNode]:
    """Return untested nodes ranked by risk: hotspot score x blast radius.

    Enriches each :class:`UntestedNode` with ``hotspot_score``,
    ``blast_radius_size``, and ``blast_files``, then sorts by
    ``(-hotspot_score, -blast_radius_size, file, line_start)``.

    Blast-radius computation is skipped for nodes with no callers (perf).

    Args:
        graph: The project call graph.
        blast_depth: Maximum hop depth for blast-radius traversal.
        top: If given, truncate result to this many entries.

    Returns:
        Sorted list of :class:`UntestedNode` with risk fields populated.
    """
    from codegraph.analysis.blast_radius import blast_radius

    nodes = find_untested(graph)
    for node in nodes:
        node.hotspot_score = _compute_hotspot_score(graph, node.id)
        if node.incoming_calls > 0:
            br = blast_radius(graph, node.id, depth=blast_depth)
            node.blast_radius_size = br.size
            node.blast_files = len(br.files)
    nodes.sort(
        key=lambda u: (-u.hotspot_score, -u.blast_radius_size, u.file, u.line_start)
    )
    if top is not None:
        nodes = nodes[:top]
    return nodes
