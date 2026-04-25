"""NetworkX adapter for the SQLiteGraphStore."""
from __future__ import annotations

from collections.abc import Iterable
from typing import cast

import networkx as nx

from codegraph.graph.schema import EdgeKind
from codegraph.graph.store_sqlite import SQLiteGraphStore


def to_digraph(store: SQLiteGraphStore) -> nx.MultiDiGraph:
    g: nx.MultiDiGraph = nx.MultiDiGraph()
    for node in store.iter_nodes():
        g.add_node(node.id, **node.model_dump())
    for edge in store.iter_edges():
        g.add_edge(edge.src, edge.dst, key=edge.kind.value, **edge.model_dump())
    return g


def subgraph_around(
    g: nx.MultiDiGraph,
    node_id: str,
    depth: int,
    direction: str = "both",
    edge_kinds: Iterable[EdgeKind] | None = None,
) -> nx.MultiDiGraph:
    """Return a MultiDiGraph of nodes within `depth` BFS hops from node_id."""
    allowed_kinds: set[str] | None = (
        {k.value for k in edge_kinds} if edge_kinds is not None else None
    )
    visited: set[str] = set()
    frontier: set[str] = {node_id}
    for _ in range(depth):
        next_frontier: set[str] = set()
        for n in frontier:
            if n not in g:
                continue
            neighbors: list[str] = []
            if direction in ("out", "both"):
                for _src, dst, data in g.out_edges(n, data=True):
                    if allowed_kinds is None or data.get("kind") in allowed_kinds:
                        neighbors.append(dst)
            if direction in ("in", "both"):
                for src, _dst, data in g.in_edges(n, data=True):
                    if allowed_kinds is None or data.get("kind") in allowed_kinds:
                        neighbors.append(src)
            for nb in neighbors:
                if nb not in visited and nb not in frontier:
                    next_frontier.add(nb)
        visited.update(frontier)
        frontier = next_frontier - visited
    visited.update(frontier)
    return cast(nx.MultiDiGraph, g.subgraph(visited).copy())
