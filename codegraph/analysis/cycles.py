"""Cycle detection over import + call subgraphs."""
from __future__ import annotations

from dataclasses import dataclass, field

import networkx as nx

from codegraph.analysis._common import filter_kinds
from codegraph.graph.schema import EdgeKind


@dataclass(frozen=True)
class Cycle:
    """A single cycle: parallel lists of node IDs and their qualnames.

    `node_ids` is the canonical machine identifier; `qualnames` is the
    human-readable rendering used in reports. Lists are the same length
    and in the same order.
    """

    node_ids: list[str]
    qualnames: list[str]


@dataclass
class CycleReport:
    import_cycles: list[Cycle] = field(default_factory=list)
    call_cycles: list[Cycle] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.import_cycles) + len(self.call_cycles)


def _qualname_for(graph: nx.MultiDiGraph, node_id: str) -> str:
    attrs = graph.nodes.get(node_id, {})
    qn = attrs.get("qualname")
    if isinstance(qn, str) and qn:
        return qn
    name = attrs.get("name")
    if isinstance(name, str) and name:
        return name
    return node_id


def _scc_cycles(graph: nx.MultiDiGraph) -> list[Cycle]:
    digraph = nx.DiGraph(graph)
    cycles: list[Cycle] = []
    for component in nx.strongly_connected_components(digraph):
        if len(component) > 1:
            node_ids = sorted(component)
            cycles.append(
                Cycle(
                    node_ids=node_ids,
                    qualnames=[_qualname_for(graph, n) for n in node_ids],
                )
            )
            continue
        # length-1 SCC: only a cycle if there's a self-loop.
        node = next(iter(component))
        if digraph.has_edge(node, node):
            cycles.append(
                Cycle(
                    node_ids=[node],
                    qualnames=[_qualname_for(graph, node)],
                )
            )
    cycles.sort(key=lambda c: (-len(c.node_ids), c.node_ids))
    return cycles


def find_cycles(graph: nx.MultiDiGraph) -> CycleReport:
    """Detect strongly-connected components in import and call subgraphs."""
    import_only = filter_kinds(graph, {EdgeKind.IMPORTS.value})
    call_only = filter_kinds(graph, {EdgeKind.CALLS.value})
    return CycleReport(
        import_cycles=_scc_cycles(import_only),
        call_cycles=_scc_cycles(call_only),
    )
