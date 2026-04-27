"""Infrastructure-component detection.

Scans IMPORTS edges in the graph to identify external services the project
talks to (Redis, BullMQ, Postgres, S3, Express, etc.) and aggregates them
into an architecture-level topology — one node per detected component plus
the source files / handlers that use it.

Pure, read-only pass: walks the in-memory graph, returns a payload dict.
No DB writes, no schema changes. Output is consumed by
``build_dashboard_payload`` to populate the dashboard's Architecture view.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any, Final

import networkx as nx

from codegraph.analysis._common import _kind_str
from codegraph.graph.schema import EdgeKind, NodeKind


ComponentKind = str  # "CACHE" | "QUEUE" | "DB" | "BROKER" | "OBJECT_STORE" | "WEB_SERVER" | "HTTP_CLIENT" | "ORM" | "MESSAGING" | "SEARCH"


_CATALOG: Final[dict[str, dict[str, str]]] = {
    "redis":            {"kind": "CACHE",        "label": "Redis",          "color": "#ef4444"},
    "ioredis":          {"kind": "CACHE",        "label": "Redis (ioredis)", "color": "#ef4444"},
    "redis-py":         {"kind": "CACHE",        "label": "Redis",          "color": "#ef4444"},
    "aioredis":         {"kind": "CACHE",        "label": "Redis (async)",  "color": "#ef4444"},
    "memcached":        {"kind": "CACHE",        "label": "Memcached",      "color": "#fb923c"},
    "pymemcache":       {"kind": "CACHE",        "label": "Memcached",      "color": "#fb923c"},

    "bullmq":           {"kind": "QUEUE",        "label": "BullMQ",         "color": "#f59e0b"},
    "bull":             {"kind": "QUEUE",        "label": "Bull",           "color": "#f59e0b"},
    "celery":           {"kind": "QUEUE",        "label": "Celery",         "color": "#f59e0b"},
    "rq":               {"kind": "QUEUE",        "label": "RQ",             "color": "#f59e0b"},
    "amqplib":          {"kind": "BROKER",       "label": "RabbitMQ",       "color": "#fb7185"},
    "kombu":            {"kind": "BROKER",       "label": "RabbitMQ",       "color": "#fb7185"},
    "pika":             {"kind": "BROKER",       "label": "RabbitMQ",       "color": "#fb7185"},
    "kafkajs":          {"kind": "BROKER",       "label": "Kafka",          "color": "#fb7185"},
    "kafka-python":     {"kind": "BROKER",       "label": "Kafka",          "color": "#fb7185"},
    "confluent-kafka":  {"kind": "BROKER",       "label": "Kafka",          "color": "#fb7185"},

    "pg":               {"kind": "DB",           "label": "PostgreSQL",     "color": "#3b82f6"},
    "postgres":         {"kind": "DB",           "label": "PostgreSQL",     "color": "#3b82f6"},
    "psycopg2":         {"kind": "DB",           "label": "PostgreSQL",     "color": "#3b82f6"},
    "psycopg":          {"kind": "DB",           "label": "PostgreSQL",     "color": "#3b82f6"},
    "asyncpg":          {"kind": "DB",           "label": "PostgreSQL",     "color": "#3b82f6"},
    "mysql2":           {"kind": "DB",           "label": "MySQL",          "color": "#06b6d4"},
    "mysql":            {"kind": "DB",           "label": "MySQL",          "color": "#06b6d4"},
    "pymysql":          {"kind": "DB",           "label": "MySQL",          "color": "#06b6d4"},
    "sqlite3":          {"kind": "DB",           "label": "SQLite",         "color": "#0ea5e9"},
    "better-sqlite3":   {"kind": "DB",           "label": "SQLite",         "color": "#0ea5e9"},
    "mongodb":          {"kind": "DB",           "label": "MongoDB",        "color": "#22c55e"},
    "mongoose":         {"kind": "ORM",          "label": "Mongoose",       "color": "#22c55e"},
    "pymongo":          {"kind": "DB",           "label": "MongoDB",        "color": "#22c55e"},
    "motor":            {"kind": "DB",           "label": "MongoDB (async)","color": "#22c55e"},
    "sqlalchemy":       {"kind": "ORM",          "label": "SQLAlchemy",     "color": "#6366f1"},
    "prisma":           {"kind": "ORM",          "label": "Prisma",         "color": "#6366f1"},
    "@prisma/client":   {"kind": "ORM",          "label": "Prisma",         "color": "#6366f1"},
    "typeorm":          {"kind": "ORM",          "label": "TypeORM",        "color": "#6366f1"},
    "sequelize":        {"kind": "ORM",          "label": "Sequelize",      "color": "#6366f1"},
    "drizzle-orm":      {"kind": "ORM",          "label": "Drizzle",        "color": "#6366f1"},
    "knex":             {"kind": "ORM",          "label": "Knex",           "color": "#6366f1"},

    "express":          {"kind": "WEB_SERVER",   "label": "Express",        "color": "#a78bfa"},
    "fastify":          {"kind": "WEB_SERVER",   "label": "Fastify",        "color": "#a78bfa"},
    "koa":              {"kind": "WEB_SERVER",   "label": "Koa",            "color": "#a78bfa"},
    "@nestjs/core":     {"kind": "WEB_SERVER",   "label": "NestJS",         "color": "#a78bfa"},
    "@nestjs/common":   {"kind": "WEB_SERVER",   "label": "NestJS",         "color": "#a78bfa"},
    "next":             {"kind": "WEB_SERVER",   "label": "Next.js",        "color": "#a78bfa"},
    "fastapi":          {"kind": "WEB_SERVER",   "label": "FastAPI",        "color": "#a78bfa"},
    "flask":            {"kind": "WEB_SERVER",   "label": "Flask",          "color": "#a78bfa"},
    "django":           {"kind": "WEB_SERVER",   "label": "Django",         "color": "#a78bfa"},
    "starlette":        {"kind": "WEB_SERVER",   "label": "Starlette",      "color": "#a78bfa"},
    "tornado":          {"kind": "WEB_SERVER",   "label": "Tornado",        "color": "#a78bfa"},

    "axios":            {"kind": "HTTP_CLIENT",  "label": "axios",          "color": "#14b8a6"},
    "got":              {"kind": "HTTP_CLIENT",  "label": "got",            "color": "#14b8a6"},
    "node-fetch":       {"kind": "HTTP_CLIENT",  "label": "node-fetch",     "color": "#14b8a6"},
    "undici":           {"kind": "HTTP_CLIENT",  "label": "undici",         "color": "#14b8a6"},
    "requests":         {"kind": "HTTP_CLIENT",  "label": "requests",       "color": "#14b8a6"},
    "httpx":            {"kind": "HTTP_CLIENT",  "label": "httpx",          "color": "#14b8a6"},
    "aiohttp":          {"kind": "HTTP_CLIENT",  "label": "aiohttp",        "color": "#14b8a6"},

    "aws-sdk":          {"kind": "OBJECT_STORE", "label": "AWS SDK",        "color": "#f59e0b"},
    "@aws-sdk/client-s3": {"kind": "OBJECT_STORE","label": "AWS S3",        "color": "#f59e0b"},
    "boto3":            {"kind": "OBJECT_STORE", "label": "AWS (boto3)",    "color": "#f59e0b"},
    "@google-cloud/storage": {"kind": "OBJECT_STORE","label": "GCS",        "color": "#3b82f6"},
    "minio":            {"kind": "OBJECT_STORE", "label": "MinIO",          "color": "#f59e0b"},

    "elasticsearch":    {"kind": "SEARCH",       "label": "Elasticsearch",  "color": "#fbbf24"},
    "@elastic/elasticsearch": {"kind": "SEARCH", "label": "Elasticsearch",  "color": "#fbbf24"},
    "meilisearch":      {"kind": "SEARCH",       "label": "Meilisearch",    "color": "#fbbf24"},
    "algoliasearch":    {"kind": "SEARCH",       "label": "Algolia",        "color": "#fbbf24"},

    "socket.io":        {"kind": "MESSAGING",    "label": "Socket.IO",      "color": "#ec4899"},
    "ws":               {"kind": "MESSAGING",    "label": "WebSocket",      "color": "#ec4899"},
    "graphql":          {"kind": "WEB_SERVER",   "label": "GraphQL",        "color": "#ec4899"},
    "@apollo/server":   {"kind": "WEB_SERVER",   "label": "Apollo Server",  "color": "#ec4899"},

    "stripe":           {"kind": "EXTERNAL_API", "label": "Stripe",         "color": "#8b5cf6"},
    "twilio":           {"kind": "EXTERNAL_API", "label": "Twilio",         "color": "#8b5cf6"},
    "sendgrid":         {"kind": "EXTERNAL_API", "label": "SendGrid",       "color": "#8b5cf6"},
    "@sendgrid/mail":   {"kind": "EXTERNAL_API", "label": "SendGrid",       "color": "#8b5cf6"},
    "nodemailer":       {"kind": "EXTERNAL_API", "label": "Email (SMTP)",   "color": "#8b5cf6"},
    "firebase-admin":   {"kind": "EXTERNAL_API", "label": "Firebase",       "color": "#8b5cf6"},
}

# Sort longer keys first so "@prisma/client" wins over "prisma" prefix tests.
_CATALOG_KEYS_LONGEST_FIRST: Final[list[str]] = sorted(
    _CATALOG.keys(), key=len, reverse=True,
)


def _root_package(target: str) -> str:
    """Return the leading package name from an import target_name.

    Python: ``redis.Redis`` -> ``redis``; ``aws.s3.client`` -> ``aws``.
    TS:     ``ioredis.default`` -> ``ioredis``;
            ``@aws-sdk/client-s3.S3Client`` -> ``@aws-sdk/client-s3``.
    """
    if not target:
        return ""
    # Scoped npm packages: keep the @scope/pkg slug intact.
    if target.startswith("@"):
        # Split into ["@scope/pkg", "rest", ...] by finding the first "." that
        # comes AFTER the slash separating scope from pkg.
        slash = target.find("/")
        if slash > 0:
            dot = target.find(".", slash)
            return target[:dot] if dot > 0 else target
    return target.split(".", 1)[0]


def _classify(target: str) -> dict[str, str] | None:
    if not target:
        return None
    # Try exact catalog match on root package.
    root = _root_package(target)
    if root in _CATALOG:
        return _CATALOG[root]
    # Try longest-prefix match (handles `@scope/pkg/sub` style imports).
    for key in _CATALOG_KEYS_LONGEST_FIRST:
        if target == key or target.startswith(key + "/") or target.startswith(key + "."):
            return _CATALOG[key]
    return None


def _file_of(graph: nx.MultiDiGraph, node_id: str) -> str:
    attrs = graph.nodes.get(node_id) or {}
    return str(attrs.get("file") or "")


def _module_id_for_file(graph: nx.MultiDiGraph, file_path: str) -> str | None:
    """Best-effort: find the MODULE node that owns a given file path."""
    for nid, attrs in graph.nodes(data=True):
        if _kind_str(attrs.get("kind")) != NodeKind.MODULE.value:
            continue
        if str(attrs.get("file") or "") == file_path:
            return nid
    return None


def _component_id(kind: str, label: str) -> str:
    return f"infra:{kind}:{label}".lower().replace(" ", "_")


def _collect_handlers(graph: nx.MultiDiGraph) -> list[dict[str, Any]]:
    """Return one entry per HANDLER node with method+path parsed from decorators."""
    out: list[dict[str, Any]] = []
    for nid, attrs in graph.nodes(data=True):
        meta = attrs.get("metadata") or {}
        if not isinstance(meta, dict):
            continue
        if meta.get("role") != "HANDLER":
            continue
        kind = _kind_str(attrs.get("kind"))
        if kind not in (NodeKind.FUNCTION.value, NodeKind.METHOD.value):
            continue
        method, path = _parse_route_from_decorators(meta.get("decorators") or [])
        out.append({
            "id": nid,
            "name": str(attrs.get("name") or ""),
            "qualname": str(attrs.get("qualname") or ""),
            "file": str(attrs.get("file") or ""),
            "line": int(attrs.get("line_start") or 0),
            "method": method,
            "path": path,
        })
    out.sort(key=lambda h: (h["file"], h["line"]))
    return out


_EXPRESS_VERB_RE: Final = None  # built lazily below
_EXPRESS_VERBS: Final[frozenset[str]] = frozenset({
    "get", "post", "put", "delete", "patch", "head", "options", "all",
})


def _strip_string_literal(text: str) -> str | None:
    """Return the inner content of a JS string literal, or None if not one."""
    s = (text or "").strip()
    if len(s) < 2:
        return None
    q = s[0]
    if q in ('"', "'", "`") and s.endswith(q):
        return s[1:-1]
    return None


def _resolve_handler_by_name(
    graph: nx.MultiDiGraph,
    name: str,
    near_file: str,
) -> str | None:
    """Find a FUNCTION/METHOD node whose name matches; prefer same-file matches."""
    if not name or not name.replace("_", "").replace("$", "").isalnum():
        return None
    same_file: str | None = None
    other: str | None = None
    for nid, attrs in graph.nodes(data=True):
        if _kind_str(attrs.get("kind")) not in (
            NodeKind.FUNCTION.value, NodeKind.METHOD.value
        ):
            continue
        if str(attrs.get("name") or "") != name:
            continue
        if str(attrs.get("file") or "") == near_file:
            return nid
        same_file = same_file or nid
        other = other or nid
    return same_file or other


def _collect_express_handlers(graph: nx.MultiDiGraph) -> list[dict[str, Any]]:
    """Extract Express/Koa-style endpoints from MODULE node metadata.

    The TS parser walks each file and stores route registrations
    (``app.get('/x', fn)``, ``router.post(...)`` etc.) under
    ``metadata.express_routes`` on its MODULE node. We read those here and
    resolve handler names to FUNCTION/METHOD nodes so reachability BFS is
    accurate.
    """
    out: list[dict[str, Any]] = []
    for nid, attrs in graph.nodes(data=True):
        if _kind_str(attrs.get("kind")) != NodeKind.MODULE.value:
            continue
        meta = attrs.get("metadata") or {}
        routes = meta.get("express_routes") or []
        if not isinstance(routes, list) or not routes:
            continue
        module_file = str(attrs.get("file") or "")
        for r in routes:
            if not isinstance(r, dict):
                continue
            method = str(r.get("method") or "").upper()
            path = str(r.get("path") or "")
            handler_name = str(r.get("handler_name") or "")
            line = int(r.get("line") or 0)
            if not method or not path:
                continue
            handler_id = (
                _resolve_handler_by_name(graph, handler_name, module_file)
                if handler_name
                else None
            )
            synth_id = f"express:{method}:{path}:{module_file}:{line}"
            out.append({
                "id": handler_id or synth_id,
                "name": handler_name or path,
                "qualname": (
                    str(graph.nodes[handler_id].get("qualname") or "")
                    if handler_id
                    else f"{module_file}:{line}"
                ),
                "file": module_file,
                "line": line,
                "method": method,
                "path": path,
                "_bfs_from": handler_id or nid,
            })
    out.sort(key=lambda h: (h["file"], h["line"]))
    return out


_HTTP_VERBS: Final[tuple[str, ...]] = (
    "get", "post", "put", "delete", "patch", "head", "options",
)


def _parse_route_from_decorators(decorators: list[Any]) -> tuple[str, str]:
    """Extract (METHOD, path) from a list of decorator-text strings.

    Best-effort regex over the captured decorator text. Returns ("", "") if
    nothing matched (the handler still appears in the list, just unlabeled).
    """
    import re
    method = ""
    path = ""
    for dec in decorators:
        text = str(dec)
        m = re.search(
            r"@\w[\w\.]*\.(get|post|put|delete|patch|head|options|route|websocket)\b",
            text,
            re.IGNORECASE,
        )
        if m:
            verb = m.group(1).lower()
            if verb in _HTTP_VERBS:
                method = verb.upper()
            elif verb == "route":
                method = "ANY"
        m2 = re.search(r"""["']([^"']+)["']""", text)
        if m2 and not path:
            path = m2.group(1)
        if method and path:
            break
    return method, path


def _bfs_infra_for_handler(
    graph: nx.MultiDiGraph,
    handler_id: str,
    file_to_components: dict[str, set[str]],
    max_depth: int = 6,
) -> list[str]:
    """Walk forward through CALLS edges from a handler, collect infra IDs hit."""
    seen: set[str] = {handler_id}
    queue: list[tuple[str, int]] = [(handler_id, 0)]
    hits: list[str] = []
    seen_components: set[str] = set()
    while queue:
        nid, depth = queue.pop(0)
        node_file = _file_of(graph, nid)
        # Any component imported in the file containing this node counts as
        # a hit, since the handler/service touches that file's symbols.
        for cid in file_to_components.get(node_file, ()):
            if cid not in seen_components:
                seen_components.add(cid)
                hits.append(cid)
        if depth >= max_depth:
            continue
        for _src, dst, data in graph.out_edges(nid, data=True):
            if _kind_str(data.get("kind")) != EdgeKind.CALLS.value:
                continue
            if dst in seen:
                continue
            if not isinstance(dst, str):
                continue
            if dst.startswith("unresolved::"):
                continue
            seen.add(dst)
            queue.append((dst, depth + 1))
    return hits


def detect_infrastructure(graph: nx.MultiDiGraph) -> dict[str, Any]:
    """Build the architecture-view payload from the graph.

    Returns a dict with three top-level keys:

    * ``components`` - one entry per detected external service. Each carries
      ``id``, ``kind``, ``label``, ``color``, ``count`` (import sites), and
      ``files`` (paths that import it).
    * ``handlers`` - one entry per HANDLER role node, with parsed
      ``method`` + ``path`` and the IDs of components reachable from it.
    * ``edges`` - aggregated USES edges from each importing module to each
      component it touches; carries ``count``.
    * ``metrics`` - summary counts.
    """
    # Pass 1: walk IMPORTS edges, classify, accumulate per-component evidence.
    components: dict[str, dict[str, Any]] = {}
    file_to_components: dict[str, set[str]] = defaultdict(set)
    edges_pair: dict[tuple[str, str], int] = defaultdict(int)

    for src, _dst, data in graph.edges(data=True):
        if _kind_str(data.get("kind")) != EdgeKind.IMPORTS.value:
            continue
        meta = data.get("metadata") or {}
        # TS edges carry both `source` and `target_name`. Python edges carry
        # only `target_name`. Try `source` first since it is the cleaner
        # package slug for TS scoped packages.
        target_str = ""
        if isinstance(meta, dict):
            target_str = str(meta.get("source") or meta.get("target_name") or "")
        if not target_str:
            continue
        info = _classify(target_str)
        if info is None:
            continue

        cid = _component_id(info["kind"], info["label"])
        if cid not in components:
            components[cid] = {
                "id": cid,
                "kind": info["kind"],
                "label": info["label"],
                "color": info["color"],
                "count": 0,
                "files": [],
                "evidence": [],
            }
        comp = components[cid]
        comp["count"] += 1
        importer_file = _file_of(graph, src)
        if importer_file:
            if importer_file not in comp["files"]:
                comp["files"].append(importer_file)
            file_to_components[importer_file].add(cid)
            edges_pair[(importer_file, cid)] += 1
        ev = f"{importer_file}:{data.get('line') or '?'} -> {target_str}"
        if len(comp["evidence"]) < 6 and ev not in comp["evidence"]:
            comp["evidence"].append(ev)

    # Pass 2: handlers (decorator-style + Express-style) + reachable components.
    decorator_handlers = _collect_handlers(graph)
    express_handlers = _collect_express_handlers(graph)
    handlers = decorator_handlers + express_handlers
    seen_handler_ids: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for h in handlers:
        key = (h["method"], h["path"], h["file"], h["line"])
        if key in seen_handler_ids:
            continue
        seen_handler_ids.add(key)
        bfs_root = h.pop("_bfs_from", None) or h["id"]
        h["components"] = _bfs_infra_for_handler(
            graph, bfs_root, file_to_components,
        )
        deduped.append(h)
    handlers = deduped

    # Pass 3: edges shaped for rendering (importer file -> component).
    edges = [
        {"source_file": fp, "target": cid, "count": n}
        for (fp, cid), n in sorted(edges_pair.items(), key=lambda kv: -kv[1])
    ]

    by_kind: dict[str, int] = defaultdict(int)
    for c in components.values():
        by_kind[c["kind"]] += 1

    return {
        "components": sorted(
            components.values(), key=lambda c: (-int(c["count"]), c["label"]),
        ),
        "handlers": handlers,
        "edges": edges,
        "metrics": {
            "components": len(components),
            "handlers": len(handlers),
            "import_sites": sum(c["count"] for c in components.values()),
            "by_kind": dict(by_kind),
        },
    }


__all__ = ["detect_infrastructure"]
