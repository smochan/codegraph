"""MCP stdio server exposing codegraph analysis tools."""
from __future__ import annotations

import asyncio
import json
from collections import deque
from collections.abc import Callable
from pathlib import Path
from typing import Any

import networkx as nx

# ---------------------------------------------------------------------------
# Graph loading — cached per-process
# ---------------------------------------------------------------------------

_CACHED_GRAPH: nx.MultiDiGraph | None = None
_CACHED_DB_PATH: Path | None = None


def _load_graph(db_path: Path | None = None) -> nx.MultiDiGraph:
    """Load (or return cached) the MultiDiGraph from *db_path*.

    If *db_path* is None, auto-resolves to ``cwd/.codegraph/graph.db``.
    A different *db_path* forces a reload.
    """
    global _CACHED_GRAPH, _CACHED_DB_PATH

    resolved = db_path or (Path.cwd() / ".codegraph" / "graph.db")
    if _CACHED_GRAPH is not None and resolved == _CACHED_DB_PATH:
        return _CACHED_GRAPH

    from codegraph.graph.store_networkx import to_digraph
    from codegraph.graph.store_sqlite import SQLiteGraphStore

    store = SQLiteGraphStore(resolved)
    g = to_digraph(store)
    store.close()

    _CACHED_GRAPH = g
    _CACHED_DB_PATH = resolved
    return g


# ---------------------------------------------------------------------------
# Pure tool-handler functions (testable without MCP machinery)
# ---------------------------------------------------------------------------

def tool_find_symbol(
    graph: nx.MultiDiGraph,
    query: str,
    kind: str | None = None,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """Substring match on qualname (case-insensitive)."""
    q = query.lower()
    results: list[dict[str, Any]] = []
    for nid, attrs in graph.nodes(data=True):
        qualname = str(attrs.get("qualname") or nid)
        if q not in qualname.lower():
            continue
        node_kind = str(attrs.get("kind") or "")
        if kind and node_kind.lower() != kind.lower():
            continue
        results.append(
            {
                "qualname": qualname,
                "kind": node_kind,
                "file": str(attrs.get("file") or ""),
                "line": int(attrs.get("line_start") or 0),
            }
        )
        if len(results) >= limit:
            break
    return results


def tool_callers(
    graph: nx.MultiDiGraph,
    qualname: str,
    depth: int = 1,
) -> list[dict[str, Any]]:
    """Reverse BFS from *qualname* over CALLS edges (who calls this?)."""
    from codegraph.analysis._common import REFERENCE_EDGE_KINDS

    # Find the node ID matching qualname
    target = _resolve_node(graph, qualname)
    if target is None:
        return []

    visited: dict[str, int] = {target: 0}
    queue: deque[str] = deque([target])
    results: list[dict[str, Any]] = []

    while queue and len(results) < 100:
        current = queue.popleft()
        current_depth = visited[current]
        if current_depth >= depth:
            continue
        for src, _dst, key in graph.in_edges(current, keys=True):
            if key not in REFERENCE_EDGE_KINDS:
                continue
            if src in visited:
                continue
            visited[src] = current_depth + 1
            queue.append(src)
            attrs = graph.nodes.get(src) or {}
            results.append(
                {
                    "qualname": str(attrs.get("qualname") or src),
                    "file": str(attrs.get("file") or ""),
                    "depth": current_depth + 1,
                }
            )

    return results


def tool_callees(
    graph: nx.MultiDiGraph,
    qualname: str,
    depth: int = 1,
) -> list[dict[str, Any]]:
    """Forward BFS from *qualname* over CALLS edges (what does this call?)."""
    from codegraph.graph.schema import EdgeKind

    target = _resolve_node(graph, qualname)
    if target is None:
        return []

    visited: dict[str, int] = {target: 0}
    queue: deque[str] = deque([target])
    results: list[dict[str, Any]] = []

    while queue and len(results) < 100:
        current = queue.popleft()
        current_depth = visited[current]
        if current_depth >= depth:
            continue
        for _src, dst, key in graph.out_edges(current, keys=True):
            if key != EdgeKind.CALLS.value:
                continue
            if dst in visited:
                continue
            visited[dst] = current_depth + 1
            queue.append(dst)
            attrs = graph.nodes.get(dst) or {}
            results.append(
                {
                    "qualname": str(attrs.get("qualname") or dst),
                    "file": str(attrs.get("file") or ""),
                    "depth": current_depth + 1,
                }
            )

    return results


def tool_blast_radius(
    graph: nx.MultiDiGraph,
    qualname: str,
    depth: int = 2,
) -> dict[str, Any]:
    """Compute blast radius for *qualname*."""
    from codegraph.analysis.blast_radius import blast_radius

    target = _resolve_node(graph, qualname)
    node_id = target if target is not None else qualname
    result = blast_radius(graph, node_id, depth=depth)
    return {
        "target": result.target,
        "size": result.size,
        "nodes": result.nodes,
        "files": sorted(result.files),
        "test_nodes": result.test_nodes,
    }


def tool_subgraph(
    graph: nx.MultiDiGraph,
    qualnames: list[str],
    depth: int = 1,
) -> dict[str, Any]:
    """Induced subgraph expanded *depth* hops outward over CALLS+IMPORTS+INHERITS."""
    from codegraph.graph.schema import EdgeKind

    allowed_kinds = {
        EdgeKind.CALLS.value,
        EdgeKind.IMPORTS.value,
        EdgeKind.INHERITS.value,
    }

    seeds: set[str] = set()
    for qn in qualnames:
        nid = _resolve_node(graph, qn)
        if nid is not None:
            seeds.add(nid)

    visited: set[str] = set()
    frontier = set(seeds)

    for _ in range(depth):
        next_frontier: set[str] = set()
        for node in frontier:
            if node not in graph:
                continue
            for _src, dst, key in graph.out_edges(node, keys=True):
                if key in allowed_kinds and dst not in visited:
                    next_frontier.add(dst)
            for src, _dst, key in graph.in_edges(node, keys=True):
                if key in allowed_kinds and src not in visited:
                    next_frontier.add(src)
        visited.update(frontier)
        frontier = next_frontier - visited

    visited.update(frontier)
    sub = graph.subgraph(visited)

    nodes_out: list[dict[str, Any]] = []
    for nid in sub.nodes():
        attrs = sub.nodes[nid]
        nodes_out.append(
            {
                "id": nid,
                "qualname": str(attrs.get("qualname") or nid),
                "kind": str(attrs.get("kind") or ""),
                "file": str(attrs.get("file") or ""),
            }
        )

    edges_out: list[dict[str, Any]] = []
    for src, dst, key in sub.edges(keys=True):
        edges_out.append({"src": src, "dst": dst, "kind": key})

    return {"nodes": nodes_out, "edges": edges_out}


def tool_dead_code(
    graph: nx.MultiDiGraph,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Return dead code candidates."""
    from codegraph.analysis.dead_code import find_dead_code

    dead = find_dead_code(graph)
    return [
        {
            "qualname": d.qualname,
            "kind": d.kind,
            "file": d.file,
            "line": d.line_start,
            "reason": d.reason,
        }
        for d in dead[:limit]
    ]


def tool_cycles(graph: nx.MultiDiGraph) -> dict[str, Any]:
    """Return import and call cycles."""
    from codegraph.analysis.cycles import find_cycles

    report = find_cycles(graph)
    return {
        "import_cycles": report.import_cycles,
        "call_cycles": report.call_cycles,
        "total": report.total,
    }


def tool_untested(
    graph: nx.MultiDiGraph,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Return untested functions/methods."""
    from codegraph.analysis.untested import find_untested

    items = find_untested(graph)
    return [
        {
            "qualname": u.qualname,
            "kind": u.kind,
            "file": u.file,
            "line": u.line_start,
            "incoming_calls": u.incoming_calls,
        }
        for u in items[:limit]
    ]


def tool_hotspots(
    graph: nx.MultiDiGraph,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """Return hotspot callables ranked by fan-in/fan-out/LOC."""
    from codegraph.analysis.hotspots import find_hotspots

    spots = find_hotspots(graph, limit=limit)
    return [
        {
            "qualname": h.qualname,
            "kind": h.kind,
            "file": h.file,
            "fan_in": h.fan_in,
            "fan_out": h.fan_out,
            "loc": h.loc,
            "score": h.score,
        }
        for h in spots
    ]


def tool_metrics(graph: nx.MultiDiGraph) -> dict[str, Any]:
    """Return aggregate graph metrics."""
    from codegraph.analysis.metrics import compute_metrics

    m = compute_metrics(graph)
    return {
        "total_nodes": m.total_nodes,
        "total_edges": m.total_edges,
        "nodes_by_kind": m.nodes_by_kind,
        "edges_by_kind": m.edges_by_kind,
        "languages": m.languages,
        "top_files_by_nodes": m.top_files_by_nodes,
        "unresolved_edges": m.unresolved_edges,
    }


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _resolve_node(graph: nx.MultiDiGraph, qualname: str) -> str | None:
    """Return the node ID for *qualname*, or None if not found.

    Tries exact match first, then substring on ``qualname`` attribute.
    """
    if qualname in graph:
        return qualname
    q = qualname.lower()
    for nid, attrs in graph.nodes(data=True):
        if str(attrs.get("qualname") or "").lower() == q:
            return str(nid)
    return None


# ---------------------------------------------------------------------------
# Tool registry — used for discovery and tests
# ---------------------------------------------------------------------------

_HandlerFn = Callable[["nx.MultiDiGraph", "dict[str, Any]"], Any]

#: Mapping of tool-name → (handler, input_schema_dict)
tool_registry: dict[str, tuple[_HandlerFn, dict[str, Any]]] = {}


def _register(
    name: str, schema: dict[str, Any]
) -> Callable[[_HandlerFn], _HandlerFn]:
    def decorator(fn: _HandlerFn) -> _HandlerFn:
        tool_registry[name] = (fn, schema)
        return fn
    return decorator


@_register(
    "find_symbol",
    {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Substring to match in qualname"},
            "kind": {"type": "string", "description": "Filter by node kind"},
            "limit": {"type": "integer", "default": 20},
        },
        "required": ["query"],
    },
)
def _handle_find_symbol(
    graph: nx.MultiDiGraph, args: dict[str, Any]
) -> Any:
    return tool_find_symbol(
        graph,
        query=str(args["query"]),
        kind=args.get("kind"),
        limit=int(args.get("limit", 20)),
    )


@_register(
    "callers",
    {
        "type": "object",
        "properties": {
            "qualname": {"type": "string"},
            "depth": {"type": "integer", "default": 1},
        },
        "required": ["qualname"],
    },
)
def _handle_callers(graph: nx.MultiDiGraph, args: dict[str, Any]) -> Any:
    return tool_callers(graph, qualname=str(args["qualname"]), depth=int(args.get("depth", 1)))


@_register(
    "callees",
    {
        "type": "object",
        "properties": {
            "qualname": {"type": "string"},
            "depth": {"type": "integer", "default": 1},
        },
        "required": ["qualname"],
    },
)
def _handle_callees(graph: nx.MultiDiGraph, args: dict[str, Any]) -> Any:
    return tool_callees(graph, qualname=str(args["qualname"]), depth=int(args.get("depth", 1)))


@_register(
    "blast_radius",
    {
        "type": "object",
        "properties": {
            "qualname": {"type": "string"},
            "depth": {"type": "integer", "default": 2},
        },
        "required": ["qualname"],
    },
)
def _handle_blast_radius(graph: nx.MultiDiGraph, args: dict[str, Any]) -> Any:
    return tool_blast_radius(
        graph, qualname=str(args["qualname"]), depth=int(args.get("depth", 2))
    )


@_register(
    "subgraph",
    {
        "type": "object",
        "properties": {
            "qualnames": {"type": "array", "items": {"type": "string"}},
            "depth": {"type": "integer", "default": 1},
        },
        "required": ["qualnames"],
    },
)
def _handle_subgraph(graph: nx.MultiDiGraph, args: dict[str, Any]) -> Any:
    return tool_subgraph(
        graph,
        qualnames=[str(q) for q in args["qualnames"]],
        depth=int(args.get("depth", 1)),
    )


@_register(
    "dead_code",
    {
        "type": "object",
        "properties": {
            "limit": {"type": "integer", "default": 50},
        },
    },
)
def _handle_dead_code(graph: nx.MultiDiGraph, args: dict[str, Any]) -> Any:
    return tool_dead_code(graph, limit=int(args.get("limit", 50)))


@_register(
    "cycles",
    {"type": "object", "properties": {}},
)
def _handle_cycles(graph: nx.MultiDiGraph, args: dict[str, Any]) -> Any:
    return tool_cycles(graph)


@_register(
    "untested",
    {
        "type": "object",
        "properties": {
            "limit": {"type": "integer", "default": 50},
        },
    },
)
def _handle_untested(graph: nx.MultiDiGraph, args: dict[str, Any]) -> Any:
    return tool_untested(graph, limit=int(args.get("limit", 50)))


@_register(
    "hotspots",
    {
        "type": "object",
        "properties": {
            "limit": {"type": "integer", "default": 20},
        },
    },
)
def _handle_hotspots(graph: nx.MultiDiGraph, args: dict[str, Any]) -> Any:
    return tool_hotspots(graph, limit=int(args.get("limit", 20)))


@_register(
    "metrics",
    {"type": "object", "properties": {}},
)
def _handle_metrics(graph: nx.MultiDiGraph, args: dict[str, Any]) -> Any:
    return tool_metrics(graph)


# ---------------------------------------------------------------------------
# MCP Server
# ---------------------------------------------------------------------------

def _build_server(name: str) -> Any:  # returns mcp.server.Server
    from mcp.server import Server
    from mcp.types import TextContent, Tool

    server: Any = Server(name)

    @server.list_tools()  # type: ignore[untyped-decorator]
    async def _list_tools() -> list[Tool]:
        return [
            Tool(name=tool_name, description=_tool_description(tool_name), inputSchema=schema)
            for tool_name, (_fn, schema) in tool_registry.items()
        ]

    @server.call_tool(validate_input=False)  # type: ignore[untyped-decorator]
    async def _call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
        if name not in tool_registry:
            raise ValueError(f"Unknown tool: {name}")
        handler_fn, _ = tool_registry[name]
        graph = _load_graph(None)
        result = handler_fn(graph, arguments)
        return [TextContent(type="text", text=json.dumps(result, indent=2))]

    return server


def _tool_description(name: str) -> str:
    descriptions = {
        "find_symbol": "Search for symbols by qualname substring",
        "callers": "Find callers of a symbol (reverse BFS)",
        "callees": "Find callees of a symbol (forward BFS)",
        "blast_radius": "Compute blast radius for a symbol",
        "subgraph": "Extract induced subgraph around symbols",
        "dead_code": "List unreferenced (dead) code",
        "cycles": "Detect import and call cycles",
        "untested": "List untested functions/methods",
        "hotspots": "List hotspot callables by fan-in/out/LOC",
        "metrics": "Return aggregate graph metrics",
    }
    return descriptions.get(name, name)


async def _serve(db_path: Path | None, server_name: str) -> None:
    import contextlib

    from mcp.server.stdio import stdio_server

    # Pre-warm the graph if db exists
    if db_path is not None or (Path.cwd() / ".codegraph" / "graph.db").exists():
        with contextlib.suppress(Exception):
            _load_graph(db_path)

    server = _build_server(server_name)
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
        )


def run(db_path: Path | None = None, server_name: str = "codegraph") -> None:
    """Synchronous entry point called from the CLI."""
    asyncio.run(_serve(db_path, server_name))
