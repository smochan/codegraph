"""End-to-end data-flow tracing across the structural / behavioural / dataflow
graph layers.

This module exposes two complementary functions:

* :func:`match_route` — given a frontend ``FETCH_CALL`` URL + method, find the
  qualname of the backend handler whose ``ROUTE`` edge matches.

* :func:`trace` — given an entry symbol (function qualname or ``url:METHOD path``
  shape), walk the call graph + cross-layer edges to produce an ordered
  :class:`DataFlow`. Implemented by DF4.

The dataclasses are stable contract — never modify the shapes here without
coordination.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

import networkx as nx

from codegraph.graph.schema import EdgeKind, NodeKind


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

    # pragma: codegraph-public-api
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

    # pragma: codegraph-public-api
    def to_dict(self) -> dict[str, Any]:
        return {
            "entry": self.entry,
            "hops": [h.to_dict() for h in self.hops],
            "confidence": self.confidence,
        }


_PLACEHOLDER_RE = re.compile(r"^(\{[^}]*\}|\$\{[^}]*\}|:[A-Za-z_][A-Za-z0-9_]*|-?\d+)$")


def _strip_query_fragment(path: str) -> str:
    """Drop ``?query`` and ``#fragment``; collapse trailing slash."""
    for sep in ("?", "#"):
        if sep in path:
            path = path.split(sep, 1)[0]
    if len(path) > 1 and path.endswith("/"):
        path = path.rstrip("/")
    return path


def _segments(path: str) -> list[str]:
    """Split ``/api/users/{id}`` into ``['api', 'users', '{id}']``."""
    return [s for s in _strip_query_fragment(path).split("/") if s]


def _is_placeholder(seg: str) -> bool:
    """A segment is a placeholder if it's purely numeric, or wrapped in
    ``{...}`` / ``${...}`` / leading ``:`` (Express style)."""
    return bool(_PLACEHOLDER_RE.match(seg))


def _normalise_path(path: str) -> list[str]:
    """Return the list of normalised segments where every placeholder
    becomes the marker ``{*}`` so two paths with different placeholder
    syntaxes compare equal segment-by-segment."""
    return ["{*}" if _is_placeholder(s) else s for s in _segments(path)]


def _path_specificity(segs: list[str]) -> int:
    """How "concrete" a path is — more literal segments means more specific.
    Used to break ties when two routes match the same fetch."""
    return sum(1 for s in segs if s != "{*}")


def _route_candidates(graph: nx.MultiDiGraph) -> list[tuple[str, str, str]]:
    """Yield ``(handler_qualname, method, path)`` for every ROUTE edge.

    ROUTE edges go from a backend handler FUNCTION/METHOD to a synthetic
    target node with id ``route::<METHOD>::<path>``. The handler qualname
    is the source node's qualname.
    """
    out: list[tuple[str, str, str]] = []
    for src, _dst, key, edata in graph.edges(keys=True, data=True):
        if key != EdgeKind.ROUTE.value:
            continue
        meta = edata.get("metadata") or {}
        if not isinstance(meta, dict):
            continue
        method = str(meta.get("method") or "").upper()
        path = str(meta.get("path") or "")
        if not method or not path:
            continue
        attrs = graph.nodes.get(src) or {}
        qn = str(attrs.get("qualname") or src)
        out.append((qn, method, path))
    return out


def _handler_param_names(graph: nx.MultiDiGraph, handler_qn: str) -> list[str]:
    """Extract parameter names for the handler function, for body-key
    overlap scoring. Looks up the node by qualname and reads
    ``metadata.params`` (populated by DF0)."""
    for _nid, attrs in graph.nodes(data=True):
        if str(attrs.get("qualname") or "") != handler_qn:
            continue
        kind = str(attrs.get("kind") or "")
        if kind not in (NodeKind.FUNCTION.value, NodeKind.METHOD.value):
            continue
        meta = attrs.get("metadata") or {}
        params = meta.get("params") or [] if isinstance(meta, dict) else []
        names: list[str] = []
        for p in params:
            if isinstance(p, dict):
                name = str(p.get("name") or "").lstrip("*")
                if name and name not in ("self", "cls"):
                    names.append(name)
        return names
    return []


def match_route(
    graph: nx.MultiDiGraph,
    fetch_url: str,
    fetch_method: str = "GET",
    *,
    body_keys: list[str] | None = None,
) -> tuple[str, float] | None:
    """Return ``(handler_qualname, confidence)`` for the backend ROUTE that
    matches this frontend fetch, or ``None`` if no route matches.

    Confidence rubric:
      * **1.0** — exact literal-segment match, no placeholders involved
      * **0.9** — placeholders in either side normalise to the same shape
      * up to **+0.05** bonus if the fetch's ``body_keys`` overlap with the
        handler's parameter names (clamped at 0.95 / 1.0 ceilings)
      * **0.5** — only a path *prefix* matches (last-resort fuzzy)
      * **None** — method mismatch or no overlap

    Trailing slashes, query strings, and fragments are stripped before
    matching. Method comparison is case-insensitive.

    When multiple routes match at the same top confidence, the more
    specific one (more literal segments) wins.
    """
    method = (fetch_method or "GET").upper()
    fetch_segs = _normalise_path(fetch_url)
    raw_fetch_segs = _segments(fetch_url)
    fetch_is_literal = all(not _is_placeholder(s) for s in raw_fetch_segs)

    best: tuple[str, float, int] | None = None  # (qn, score, specificity)

    for handler_qn, route_method, route_path in _route_candidates(graph):
        if route_method != method:
            continue
        route_segs = _normalise_path(route_path)
        raw_route_segs = _segments(route_path)
        route_is_literal = all(not _is_placeholder(s) for s in raw_route_segs)

        if fetch_segs == route_segs:
            base = 1.0 if (fetch_is_literal and route_is_literal) else 0.9
            specificity = _path_specificity(route_segs)
        elif (
            len(fetch_segs) >= len(route_segs)
            and fetch_segs[: len(route_segs)] == route_segs
            and len(route_segs) > 0
        ):
            base = 0.5
            specificity = _path_specificity(route_segs)
        else:
            continue

        # Body-key bonus: any overlap with handler params nudges score up.
        if body_keys:
            param_names = _handler_param_names(graph, handler_qn)
            overlap = set(body_keys) & set(param_names)
            if overlap:
                cap = 1.0 if base >= 1.0 else (0.95 if base >= 0.9 else 0.7)
                base = min(cap, base + 0.05)

        if best is None or base > best[1] or (
            base == best[1] and specificity > best[2]
        ):
            best = (handler_qn, base, specificity)

    if best is None:
        return None
    return (best[0], best[1])


_FRONTEND_EXTS = (".tsx", ".jsx")
_FETCH_ENTRY_RE = re.compile(
    r"^\s*(?:url:\s*)?(GET|POST|PUT|DELETE|PATCH|HEAD|OPTIONS|TRACE|WEBSOCKET)\s+(\S+)\s*$",
    re.IGNORECASE,
)


def _resolve_entry_node(
    graph: nx.MultiDiGraph, entry: str
) -> str | None:
    """Find a node id matching the given qualname (exact, case-insensitive)."""
    target = entry.strip()
    for nid, attrs in graph.nodes(data=True):
        qn = str(attrs.get("qualname") or "")
        if qn == target:
            return str(nid)
    # Case-insensitive fallback
    lower = target.lower()
    for nid, attrs in graph.nodes(data=True):
        qn = str(attrs.get("qualname") or "")
        if qn.lower() == lower:
            return str(nid)
    return None


def _layer_for(attrs: dict[str, Any]) -> str:
    """Pick a layer label from a node's attrs."""
    metadata = attrs.get("metadata") or {}
    role = ""
    if isinstance(metadata, dict):
        role_val = metadata.get("role")
        role = str(role_val) if role_val else ""
    if role == "REPO":
        return "db"
    if role == "COMPONENT":
        return "frontend"
    file_path = str(attrs.get("file") or "").lower()
    if any(file_path.endswith(ext) for ext in _FRONTEND_EXTS):
        return "frontend"
    return "backend"


def _hop_from_node(
    graph: nx.MultiDiGraph,
    node_id: str,
    *,
    args: list[str] | None = None,
    kwargs: dict[str, str] | None = None,
    confidence: float = 1.0,
) -> FlowHop:
    attrs = graph.nodes.get(node_id) or {}
    metadata = attrs.get("metadata") or {}
    role = None
    if isinstance(metadata, dict):
        role_val = metadata.get("role")
        if role_val:
            role = str(role_val)
    return FlowHop(
        layer=_layer_for(attrs),
        qualname=str(attrs.get("qualname") or node_id),
        file=str(attrs.get("file") or ""),
        line=int(attrs.get("line_start") or 0),
        args=list(args or []),
        kwargs=dict(kwargs or {}),
        role=role,
        confidence=confidence,
    )


def _outgoing_calls(
    graph: nx.MultiDiGraph, node_id: str
) -> list[tuple[str, dict[str, Any]]]:
    """Return [(target_id, edge_metadata)] for outgoing CALLS edges."""
    out: list[tuple[str, dict[str, Any]]] = []
    for _src, dst, key, edata in graph.out_edges(node_id, keys=True, data=True):
        if key == EdgeKind.CALLS.value:
            meta = edata.get("metadata") or {}
            out.append((str(dst), meta if isinstance(meta, dict) else {}))
    return out


def _outgoing_data_edges(
    graph: nx.MultiDiGraph, node_id: str
) -> list[tuple[str, str]]:
    """Return [(target_id, edge_kind)] for READS_FROM / WRITES_TO edges."""
    out: list[tuple[str, str]] = []
    for _src, dst, key in graph.out_edges(node_id, keys=True):
        if key in (EdgeKind.READS_FROM.value, EdgeKind.WRITES_TO.value):
            out.append((str(dst), str(key)))
    return out


def _outgoing_fetches(
    graph: nx.MultiDiGraph, node_id: str
) -> list[dict[str, Any]]:
    """Return list of FETCH_CALL edge metadata dicts originating from this node."""
    out: list[dict[str, Any]] = []
    for _src, _dst, key, edata in graph.out_edges(node_id, keys=True, data=True):
        if key == EdgeKind.FETCH_CALL.value:
            meta = edata.get("metadata") or {}
            if isinstance(meta, dict):
                out.append(meta)
    return out


def _edge_args(meta: dict[str, Any]) -> tuple[list[str], dict[str, str]]:
    args_raw = meta.get("args") or []
    kwargs_raw = meta.get("kwargs") or {}
    args = [str(a) for a in args_raw] if isinstance(args_raw, list) else []
    kwargs: dict[str, str] = {}
    if isinstance(kwargs_raw, dict):
        kwargs = {str(k): str(v) for k, v in kwargs_raw.items()}
    return args, kwargs


def trace(
    graph: nx.MultiDiGraph,
    entry: str,
    *,
    max_depth: int = 6,
) -> DataFlow | None:
    """Trace a data-flow starting from ``entry``.

    ``entry`` may be:

      * a fully-qualified symbol name — walk forwards over CALLS edges
      * ``"METHOD /path"`` (or ``"url:METHOD /path"``) — find a backend handler
        via :func:`match_route` and walk from there

    Returns ``None`` when the entry cannot be located.

    Hop construction:
      * each visited node becomes a :class:`FlowHop`
      * args/kwargs come from the *incoming* CALLS edge that brought us here
      * READS_FROM / WRITES_TO edges become trailing ``layer=db`` hops
      * outgoing FETCH_CALL edges trigger a cross-layer match via
        :func:`match_route`; if no match, the partial chain is returned with
        confidence dropped accordingly
      * cycle detection: already-visited nodes are skipped silently
      * stop after ``max_depth`` outgoing hops
    """
    # ---- Resolve the starting node --------------------------------------
    fetch_match = _FETCH_ENTRY_RE.match(entry)
    start_node: str | None = None
    initial_confidence = 1.0
    initial_args: list[str] = []
    initial_kwargs: dict[str, str] = {}
    initial_method: str | None = None
    initial_path: str | None = None

    if fetch_match:
        method = fetch_match.group(1).upper()
        path = fetch_match.group(2)
        result = match_route(graph, path, method)
        if result is None:
            return DataFlow(entry=entry, hops=[], confidence=0.0)
        handler_qn, conf = result
        start_node = _resolve_entry_node(graph, handler_qn)
        initial_confidence = conf
        initial_method = method
        initial_path = path
    else:
        start_node = _resolve_entry_node(graph, entry)

    if start_node is None:
        return None

    # ---- Walk the graph -------------------------------------------------
    hops: list[FlowHop] = []
    visited: set[str] = set()

    first_hop = _hop_from_node(
        graph,
        start_node,
        args=initial_args,
        kwargs=initial_kwargs,
        confidence=initial_confidence,
    )
    if initial_method is not None:
        first_hop.method = initial_method
    if initial_path is not None:
        first_hop.path = initial_path
    hops.append(first_hop)
    visited.add(start_node)

    current = start_node
    confidences: list[float] = [initial_confidence]
    depth = 0

    while depth < max_depth:
        # 1. Cross-layer fetch transition (if any)
        fetches = _outgoing_fetches(graph, current)
        consumed_via_fetch = False
        for fmeta in fetches:
            url = str(fmeta.get("url") or "")
            method = str(fmeta.get("method") or "GET")
            body_keys_raw = fmeta.get("body_keys") or []
            body_keys = (
                [str(k) for k in body_keys_raw]
                if isinstance(body_keys_raw, list)
                else None
            )
            result = match_route(graph, url, method, body_keys=body_keys)
            if result is None:
                continue
            handler_qn, conf = result
            handler_node = _resolve_entry_node(graph, handler_qn)
            if handler_node is None or handler_node in visited:
                continue
            hop = _hop_from_node(
                graph,
                handler_node,
                args=[],
                kwargs={},
                confidence=conf,
            )
            hop.method = method
            hop.path = url
            hops.append(hop)
            visited.add(handler_node)
            confidences.append(conf)
            current = handler_node
            consumed_via_fetch = True
            break  # follow one fetch per hop
        if consumed_via_fetch:
            depth += 1
            continue

        # 2. Standard CALLS traversal — pick the first outgoing edge
        callees = _outgoing_calls(graph, current)
        next_step: tuple[str, list[str], dict[str, str]] | None = None
        for dst, meta in callees:
            if dst in visited:
                continue
            args, kwargs = _edge_args(meta)
            next_step = (dst, args, kwargs)
            break

        if next_step is not None:
            dst, args, kwargs = next_step
            hop = _hop_from_node(
                graph,
                dst,
                args=args,
                kwargs=kwargs,
                confidence=1.0,
            )
            hops.append(hop)
            visited.add(dst)
            confidences.append(1.0)
            current = dst
            depth += 1
            continue

        # 3. Terminal data edges (READS_FROM / WRITES_TO) — emit and stop
        for dst, kind in _outgoing_data_edges(graph, current):
            if dst in visited:
                continue
            db_attrs = graph.nodes.get(dst) or {}
            db_qn = str(db_attrs.get("qualname") or dst)
            db_hop = FlowHop(
                layer="db",
                qualname=db_qn,
                file=str(db_attrs.get("file") or ""),
                line=int(db_attrs.get("line_start") or 0),
                role="REPO",
                confidence=1.0,
            )
            db_hop.kwargs = {"op": kind}
            hops.append(db_hop)
            visited.add(dst)
            confidences.append(1.0)
        break

    final_conf = min(confidences) if confidences else 0.0
    return DataFlow(entry=entry, hops=hops, confidence=final_conf)


__all__ = ["DataFlow", "FlowHop", "match_route", "trace"]
