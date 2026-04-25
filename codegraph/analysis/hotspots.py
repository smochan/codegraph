"""Hotspot detection: top-N nodes by fan-in / fan-out / size."""
from __future__ import annotations

from dataclasses import dataclass

import networkx as nx

from codegraph.analysis._common import _kind_str
from codegraph.graph.schema import EdgeKind, NodeKind

_CALLABLE_KINDS: frozenset[str] = frozenset(
    {NodeKind.FUNCTION.value, NodeKind.METHOD.value}
)


@dataclass
class Hotspot:
    id: str
    name: str
    qualname: str
    kind: str
    file: str
    fan_in: int
    fan_out: int
    loc: int

    @property
    def score(self) -> int:
        return self.fan_in * 2 + self.fan_out + self.loc // 50


def find_hotspots(
    graph: nx.MultiDiGraph,
    *,
    limit: int = 20,
    kinds: frozenset[str] = _CALLABLE_KINDS,
) -> list[Hotspot]:
    """Return top-N callable hotspots ranked by combined fan-in / fan-out / LOC."""
    rows: list[Hotspot] = []
    for nid, attrs in graph.nodes(data=True):
        kind = _kind_str(attrs.get("kind"))
        if kind not in kinds:
            continue
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
        rows.append(
            Hotspot(
                id=nid,
                name=str(attrs.get("name") or ""),
                qualname=str(attrs.get("qualname") or ""),
                kind=kind,
                file=str(attrs.get("file") or ""),
                fan_in=fan_in,
                fan_out=fan_out,
                loc=loc,
            )
        )
    rows.sort(key=lambda h: (-h.score, -h.fan_in, h.qualname))
    return rows[:limit]
