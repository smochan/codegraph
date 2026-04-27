"""End-to-end data-flow tracing across the structural / behavioural / dataflow
graph layers.

This module exposes two complementary functions:

* :func:`match_route` — given a frontend ``FETCH_CALL`` URL + method, find the
  qualname of the backend handler whose ``ROUTE`` edge matches. Implemented by
  the DF3 stitcher (URL pattern matching with parameter normalisation).

* :func:`trace` — given an entry symbol (function qualname or ``url:METHOD path``
  shape), walk the call graph + cross-layer edges to produce an ordered
  :class:`DataFlow`. Implemented by DF4.

The dataclasses are stable contract — agents fill in the function bodies but
never modify the shapes here without coordination.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import networkx as nx


@dataclass
class FlowHop:
    """One step in a traced data-flow.

    ``layer`` distinguishes ``frontend`` / ``backend`` / ``db`` so consumers
    (CLI, MCP, dashboard) can render lanes. ``confidence`` is the per-hop match
    quality — 1.0 for direct call-graph edges, lower for fuzzy URL matches.
    """

    layer: str  # "frontend" | "backend" | "db"
    qualname: str
    file: str = ""
    line: int = 0
    method: str | None = None  # HTTP verb, when applicable
    path: str | None = None  # URL path, when applicable
    args: list[str] = field(default_factory=list)
    kwargs: dict[str, str] = field(default_factory=dict)
    role: str | None = None  # HANDLER / SERVICE / COMPONENT / REPO if known
    confidence: float = 1.0

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "layer": self.layer,
            "qualname": self.qualname,
            "file": self.file,
            "line": self.line,
            "args": list(self.args),
            "kwargs": dict(self.kwargs),
            "confidence": self.confidence,
        }
        if self.method is not None:
            out["method"] = self.method
        if self.path is not None:
            out["path"] = self.path
        if self.role is not None:
            out["role"] = self.role
        return out


@dataclass
class DataFlow:
    """Ordered sequence of :class:`FlowHop` objects describing one trace.

    ``confidence`` is the minimum across hops — the chain is only as strong as
    its weakest match.
    """

    entry: str
    hops: list[FlowHop] = field(default_factory=list)
    confidence: float = 1.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "entry": self.entry,
            "hops": [h.to_dict() for h in self.hops],
            "confidence": self.confidence,
        }


def match_route(
    graph: nx.MultiDiGraph,
    fetch_url: str,
    fetch_method: str = "GET",
) -> tuple[str, float] | None:
    """Return ``(handler_qualname, confidence)`` for the route matching this
    frontend fetch, or ``None`` if no route matches.

    Implemented by DF3 (agent A1). Stub returns ``None`` so DF4 can build
    against the contract before A1 lands.

    Confidence rubric (DF3 will encode):
      * 1.0 — exact path + method match
      * 0.9 — path with placeholders matches (``/users/{id}`` vs ``/users/42``)
      * 0.7 — method matches, path matches with body-key heuristic
      * 0.5 — only path prefix matches (last-resort)
    """
    return None


def trace(
    graph: nx.MultiDiGraph,
    entry: str,
    *,
    max_depth: int = 6,
) -> DataFlow | None:
    """Trace a data-flow starting from ``entry``.

    ``entry`` may be:

      * a fully-qualified symbol name — walk forwards over CALLS edges
      * ``"url:METHOD /path"`` — start from a frontend ``FETCH_CALL`` and stitch
        through the matching ROUTE handler

    Returns ``None`` when ``entry`` cannot be located in the graph.

    Implemented by DF4 (agent A2). Stub returns ``None`` so the CLI / MCP layer
    can register the public surface.
    """
    return None


__all__ = ["DataFlow", "FlowHop", "match_route", "trace"]
