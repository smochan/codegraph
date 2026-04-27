"""Architectural role classification for FUNCTION/METHOD/CLASS nodes.

Stamps ``metadata["role"]`` with one of:

* ``HANDLER`` - HTTP/route/endpoint entry points (FastAPI, Flask, NestJS,
  Next.js route files, Express-style decorators).
* ``SERVICE`` - business-logic classes (``*Service`` suffix, ``@Injectable``)
  and their methods.
* ``COMPONENT`` - React components (TS/JS only).
* ``REPO`` - data-access classes (``*Repository`` suffix or SQLAlchemy
  Session-using classes).

Conflict priority: HANDLER > COMPONENT > SERVICE > REPO. Whichever fires
first wins; subsequent rules do not overwrite.

This pass is purely additive: it never mutates parser-emitted attributes
besides the ``role`` key inside a node's ``metadata`` dict.
"""
from __future__ import annotations

import re
from typing import Final

import networkx as nx

from codegraph.analysis._common import _kind_str
from codegraph.graph.schema import EdgeKind, NodeKind

Role = str  # "HANDLER" | "SERVICE" | "COMPONENT" | "REPO"

HANDLER: Final[Role] = "HANDLER"
SERVICE: Final[Role] = "SERVICE"
COMPONENT: Final[Role] = "COMPONENT"
REPO: Final[Role] = "REPO"

_ROLE_PRIORITY: Final[dict[Role, int]] = {
    HANDLER: 4,
    COMPONENT: 3,
    SERVICE: 2,
    REPO: 1,
}

# HTTP verb decorator pattern: matches @anything.get / @anything.post / etc.,
# also @anything.route / @anything.websocket / @anything.endpoint.
_HTTP_VERBS: Final[tuple[str, ...]] = (
    "get", "post", "put", "delete", "patch", "head", "options",
    "route", "websocket", "endpoint",
)
_HTTP_DECORATOR_RE: Final[re.Pattern[str]] = re.compile(
    r"@[\w\.]+\.(?:" + "|".join(_HTTP_VERBS) + r")\b",
)
# Substring fallback: catches things like @route(...) or @endpoint(...).
_ROUTE_SUBSTRINGS: Final[tuple[str, ...]] = ("route", "endpoint")

_TS_LIKE_LANGS: Final[frozenset[str]] = frozenset(
    {"typescript", "javascript", "tsx", "jsx"}
)
_TSX_EXTS: Final[tuple[str, ...]] = (".tsx", ".jsx")


def _decorators(attrs: dict[str, object]) -> list[str]:
    metadata = attrs.get("metadata") or {}
    if not isinstance(metadata, dict):
        return []
    raw = metadata.get("decorators") or []
    if not isinstance(raw, list):
        return []
    return [str(x) for x in raw]


def _is_http_decorator(text: str) -> bool:
    if _HTTP_DECORATOR_RE.search(text):
        return True
    # Substring match (case-insensitive) on the decorator name itself.
    lowered = text.lower()
    return any(sub in lowered for sub in _ROUTE_SUBSTRINGS)


def _has_handler_decorator(decorators: list[str]) -> bool:
    return any(_is_http_decorator(d) for d in decorators)


def _has_injectable_decorator(decorators: list[str]) -> bool:
    return any(d.lstrip("@").startswith("Injectable") for d in decorators)


def _has_controller_decorator(decorators: list[str]) -> bool:
    return any(d.lstrip("@").startswith("Controller") for d in decorators)


def _is_next_route_file(file_path: str) -> bool:
    """Match Next.js app router or pages/api conventions."""
    norm = file_path.replace("\\", "/")
    if re.search(r"(?:^|/)app/.*?/route\.(?:ts|js|tsx|jsx)$", norm):
        return True
    return bool(re.search(r"(?:^|/)pages/api/.*\.(?:ts|js|tsx|jsx)$", norm))


def _is_tsx_file(file_path: str) -> bool:
    norm = file_path.lower()
    return norm.endswith(_TSX_EXTS)


def _is_pascal_case(name: str) -> bool:
    return bool(name) and name[0].isupper() and not name.isupper()


def _has_params(attrs: dict[str, object]) -> bool:
    sig = attrs.get("signature")
    if not isinstance(sig, str):
        return False
    # Heuristic: a parameter list with at least one non-empty token between
    # parentheses. ``foo()`` has no params; ``foo(props)`` does.
    m = re.search(r"\(([^)]*)\)", sig)
    if not m:
        return False
    return bool(m.group(1).strip())


def _class_inherits_react_component(
    graph: nx.MultiDiGraph, class_id: str
) -> bool:
    """True if class has an INHERITS edge to React.Component / Component."""
    for _src, _dst, _key, data in graph.out_edges(class_id, keys=True, data=True):
        if data.get("kind") != EdgeKind.INHERITS.value:
            continue
        target = ""
        meta = data.get("metadata") or {}
        if isinstance(meta, dict):
            target = str(meta.get("target_name") or "")
        if not target:
            continue
        if target in {"React.Component", "Component", "React.PureComponent",
                      "PureComponent"}:
            return True
    return False


def _members_of_class(
    graph: nx.MultiDiGraph, class_id: str
) -> list[str]:
    """Return method/function nodes whose DEFINED_IN edge points to class."""
    members: list[str] = []
    for src, _dst, _key, data in graph.in_edges(class_id, keys=True, data=True):
        if data.get("kind") != EdgeKind.DEFINED_IN.value:
            continue
        attrs = graph.nodes.get(src) or {}
        kind = _kind_str(attrs.get("kind"))
        if kind in (NodeKind.METHOD.value, NodeKind.FUNCTION.value):
            members.append(src)
    return members


def _enclosing_class(
    graph: nx.MultiDiGraph, node_id: str
) -> str | None:
    """Return the CLASS node id this method is DEFINED_IN, if any."""
    for _src, dst, _key, data in graph.out_edges(node_id, keys=True, data=True):
        if data.get("kind") != EdgeKind.DEFINED_IN.value:
            continue
        attrs = graph.nodes.get(dst) or {}
        if _kind_str(attrs.get("kind")) == NodeKind.CLASS.value:
            return str(dst)
    return None


def _set_role(
    graph: nx.MultiDiGraph, node_id: str, role: Role
) -> bool:
    """Set role on the node, respecting priority. Returns True if changed."""
    attrs = graph.nodes.get(node_id)
    if attrs is None:
        return False
    metadata = attrs.get("metadata")
    if not isinstance(metadata, dict):
        metadata = {}
        attrs["metadata"] = metadata
    current = metadata.get("role")
    if (
        isinstance(current, str)
        and current in _ROLE_PRIORITY
        and _ROLE_PRIORITY[role] <= _ROLE_PRIORITY[current]
    ):
        return False
    metadata["role"] = role
    return True


def _classify_handler(
    graph: nx.MultiDiGraph, node_id: str, attrs: dict[str, object]
) -> bool:
    kind = _kind_str(attrs.get("kind"))
    if kind not in (NodeKind.FUNCTION.value, NodeKind.METHOD.value):
        return False
    decorators = _decorators(attrs)
    if _has_handler_decorator(decorators):
        return _set_role(graph, node_id, HANDLER)
    # NestJS: methods on a class decorated with @Controller(...) are handlers.
    if kind == NodeKind.METHOD.value:
        cls_id = _enclosing_class(graph, node_id)
        if cls_id is not None:
            cls_attrs = graph.nodes.get(cls_id) or {}
            if _has_controller_decorator(_decorators(cls_attrs)):
                return _set_role(graph, node_id, HANDLER)
    # Next.js app/**/route.{ts,js} or pages/api/**.{ts,js} files.
    if kind == NodeKind.FUNCTION.value:
        file_path = str(attrs.get("file") or "")
        language = str(attrs.get("language") or "").lower()
        if language in _TS_LIKE_LANGS and _is_next_route_file(file_path):
            return _set_role(graph, node_id, HANDLER)
    return False


def _classify_service_class(
    graph: nx.MultiDiGraph, node_id: str, attrs: dict[str, object]
) -> bool:
    if _kind_str(attrs.get("kind")) != NodeKind.CLASS.value:
        return False
    name = str(attrs.get("name") or "")
    if name.endswith("Service"):
        return _set_role(graph, node_id, SERVICE)
    if _has_injectable_decorator(_decorators(attrs)):
        return _set_role(graph, node_id, SERVICE)
    return False


def _classify_repo_class(
    graph: nx.MultiDiGraph, node_id: str, attrs: dict[str, object]
) -> bool:
    if _kind_str(attrs.get("kind")) != NodeKind.CLASS.value:
        return False
    name = str(attrs.get("name") or "")
    if name.endswith("Repository"):
        return _set_role(graph, node_id, REPO)
    return False


def _classify_component(
    graph: nx.MultiDiGraph, node_id: str, attrs: dict[str, object]
) -> bool:
    """COMPONENT detection (TS/JS only).

    Rules:
    * CLASS extending ``React.Component`` / ``Component`` / ``PureComponent``.
    * FUNCTION whose file extension is ``.tsx``/``.jsx`` AND name is
      PascalCase AND it accepts at least one parameter.
    """
    language = str(attrs.get("language") or "").lower()
    if language not in _TS_LIKE_LANGS:
        return False
    kind = _kind_str(attrs.get("kind"))
    file_path = str(attrs.get("file") or "")
    if kind == NodeKind.CLASS.value:
        if _class_inherits_react_component(graph, node_id):
            return _set_role(graph, node_id, COMPONENT)
        return False
    if kind == NodeKind.FUNCTION.value:
        if not _is_tsx_file(file_path):
            return False
        name = str(attrs.get("name") or "")
        if not _is_pascal_case(name):
            return False
        if not _has_params(attrs):
            return False
        return _set_role(graph, node_id, COMPONENT)
    return False


def _propagate_class_role_to_members(
    graph: nx.MultiDiGraph, class_id: str, role: Role
) -> int:
    count = 0
    for member_id in _members_of_class(graph, class_id):
        # Methods that are already classified at higher priority (HANDLER)
        # keep their own role thanks to _set_role's priority check.
        if _set_role(graph, member_id, role):
            count += 1
    return count


def classify_roles(graph: nx.MultiDiGraph) -> int:
    """Walk the graph and stamp metadata['role'] on FUNCTION/METHOD/CLASS.

    Returns the number of nodes that received a non-None role assignment
    (counts each node at most once, even if multiple rules matched).
    """
    annotated: set[str] = set()

    # Pass 1: HANDLERs first (highest priority on functions/methods).
    for nid, attrs in graph.nodes(data=True):
        if _classify_handler(graph, nid, attrs):
            annotated.add(nid)

    # Pass 2: classes — REPO, SERVICE, COMPONENT (CLASS branch).
    service_classes: list[str] = []
    repo_classes: list[str] = []
    for nid, attrs in graph.nodes(data=True):
        kind = _kind_str(attrs.get("kind"))
        if kind != NodeKind.CLASS.value:
            continue
        # COMPONENT class extending React.Component takes priority over
        # SERVICE/REPO suffix coincidences.
        if _classify_component(graph, nid, attrs):
            annotated.add(nid)
            continue
        if _classify_service_class(graph, nid, attrs):
            annotated.add(nid)
            service_classes.append(nid)
            continue
        if _classify_repo_class(graph, nid, attrs):
            annotated.add(nid)
            repo_classes.append(nid)

    # Pass 3: COMPONENT functions.
    for nid, attrs in graph.nodes(data=True):
        if _kind_str(attrs.get("kind")) != NodeKind.FUNCTION.value:
            continue
        if _classify_component(graph, nid, attrs):
            annotated.add(nid)

    # Pass 4: propagate SERVICE/REPO to class members. _set_role respects
    # priority, so methods already tagged HANDLER stay HANDLER.
    for cls_id in service_classes:
        for member_id in _members_of_class(graph, cls_id):
            if _set_role(graph, member_id, SERVICE):
                annotated.add(member_id)
    for cls_id in repo_classes:
        for member_id in _members_of_class(graph, cls_id):
            if _set_role(graph, member_id, REPO):
                annotated.add(member_id)

    return len(annotated)


__all__ = ["COMPONENT", "HANDLER", "REPO", "SERVICE", "classify_roles"]
