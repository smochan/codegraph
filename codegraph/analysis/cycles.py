"""Cycle detection over import + call subgraphs."""
from __future__ import annotations

from dataclasses import dataclass, field

import networkx as nx

from codegraph.analysis._common import filter_kinds
from codegraph.graph.schema import EdgeKind


@dataclass
class CycleReport:
    import_cycles: list[list[str]] = field(default_factory=list)
    call_cycles: list[list[str]] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.import_cycles) + len(self.call_cycles)


def _scc_cycles(graph: nx.MultiDiGraph) -> list[list[str]]:
    digraph = nx.DiGraph(graph)
    cycles: list[list[str]] = []
    for component in nx.strongly_connected_components(digraph):
        if len(component) > 1:
            cycles.append(sorted(component))
            continue
        # length-1 SCC: only a cycle if there's a self-loop.
        node = next(iter(component))
        if digraph.has_edge(node, node):
            cycles.append([node])
    cycles.sort(key=lambda c: (-len(c), c))
    return cycles


def find_cycles(graph: nx.MultiDiGraph) -> CycleReport:
    """Detect strongly-connected components in import and call subgraphs."""
    import_only = filter_kinds(graph, {EdgeKind.IMPORTS.value})
    call_only = filter_kinds(graph, {EdgeKind.CALLS.value})
    return CycleReport(
        import_cycles=_scc_cycles(import_only),
        call_cycles=_scc_cycles(call_only),
    )
