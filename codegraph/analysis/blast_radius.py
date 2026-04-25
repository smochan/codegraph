"""Blast radius: reverse-reachable set of a node via reference edges."""
from __future__ import annotations

from dataclasses import dataclass, field

import networkx as nx

from codegraph.analysis._common import REFERENCE_EDGE_KINDS, in_test_module


@dataclass
class BlastRadiusResult:
    target: str
    nodes: list[str] = field(default_factory=list)
    files: set[str] = field(default_factory=set)
    test_nodes: list[str] = field(default_factory=list)
    depth: int | None = None

    @property
    def size(self) -> int:
        return len(self.nodes)


def blast_radius(
    graph: nx.MultiDiGraph,
    node_id: str,
    depth: int | None = None,
) -> BlastRadiusResult:
    """Return the set of nodes that transitively reference ``node_id``.

    A node ``B`` is in the blast radius of ``A`` iff there is a path from
    ``B`` to ``A`` along CALLS / IMPORTS / INHERITS / IMPLEMENTS edges. The
    target itself is excluded from ``nodes``.
    """
    result = BlastRadiusResult(target=node_id, depth=depth)
    if node_id not in graph:
        return result

    visited: set[str] = {node_id}
    frontier: set[str] = {node_id}
    hops = 0
    while frontier and (depth is None or hops < depth):
        next_frontier: set[str] = set()
        for current in frontier:
            for src, _dst, key in graph.in_edges(current, keys=True):
                if key not in REFERENCE_EDGE_KINDS:
                    continue
                if src in visited:
                    continue
                next_frontier.add(src)
        visited |= next_frontier
        frontier = next_frontier
        hops += 1

    visited.discard(node_id)
    result.nodes = sorted(visited)
    for nid in visited:
        attrs = graph.nodes.get(nid) or {}
        if attrs.get("file"):
            result.files.add(str(attrs["file"]))
        if in_test_module(graph, nid):
            result.test_nodes.append(nid)
    return result
