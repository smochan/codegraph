"""Taint propagation engine.

Spec: docs/GAP_ANALYSIS_VS_LLM_REVIEWER.md §Capability A

Exposes :func:`propagate` which walks the intra-procedural data-flow edges
(DATA_ASSIGN, DATA_ARG, DATA_RETURN) emitted by the C1 Python extractor,
plus one inter-procedural hop via CALLS edges, and reports :class:`TaintFinding`
objects wherever tainted data reaches a dangerous sink without being sanitized.

**Scope (explicitly bounded):**
* Intra-procedural flow within a single function.
* One inter-procedural hop: tainted PARAMETER/VARIABLE → DATA_ARG sentinel →
  resolved callee PARAMETER node (matched via CALLS edges or tail-qualname).
* Call-result sources: VARIABLE nodes assigned from ``unresolved::ret::<callee>``
  where the callee matches a source regex.
* Route-param sources: PARAMETER nodes of functions with incoming ROUTE edges.
* Sanitizer absorption: taint tokens carry the set of cleared sink classes;
  at sink-time suppressed when the sink's class is covered.

**Intentional limitations (documented, not bugs):**
* No field/attribute sensitivity (``obj.field = tainted`` not tracked).
* No interprocedural return flow (callee return values → caller result variable
  is handled via ``unresolved::ret::`` sentinels in C1, not real return nodes).
* No context-sensitivity: if a helper function is called with both tainted and
  clean args, the callee's parameter is always considered tainted on the first
  tainted call observed.
* Flow-insensitivity within branches: both arms of an if/else are treated as
  reachable.
* Confidence degrades x0.8 for tail-match inter-procedural hops and x0.9 when
  position-only matching (no name confirmation).
"""
from __future__ import annotations

import re
from collections import deque
from dataclasses import dataclass, field
from typing import Any

import networkx as nx

from codegraph.analysis.taint_catalog import SourceSpec, TaintCatalog
from codegraph.graph.schema import EdgeKind, NodeKind

# ---------------------------------------------------------------------------
# Public dataclasses
# ---------------------------------------------------------------------------


@dataclass
class TaintHop:
    """One step in a taint witness path."""

    qualname: str
    file: str
    line: int
    edge_kind: str  # EdgeKind value string


@dataclass
class TaintFinding:
    """A complete taint finding: source → path → sink.

    Attributes:
        source_qualname:   Qualname of the seed node (PARAMETER / VARIABLE).
        source_class:      Semantic class label of the source.
        sink_callee:       Callee text of the dangerous call.
        sink_class:        Semantic class label of the sink.
        sink_file:         File where the sink call occurs.
        sink_line:         Line number of the sink call.
        path:              Ordered witness path from source to the tainted node
                           that flows into the sink.
        severity:          Severity string from the matching SinkSpec.
        confidence:        Float 0.0-1.0; degrades on indirect hops.
        sanitized:         Always False for reported findings.  Sanitized paths
                           are absorbed and not returned.
    """

    source_qualname: str
    source_class: str
    sink_callee: str
    sink_class: str
    sink_file: str
    sink_line: int
    path: list[TaintHop] = field(default_factory=list)
    severity: str = "high"
    confidence: float = 1.0
    sanitized: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_qualname": self.source_qualname,
            "source_class": self.source_class,
            "sink_callee": self.sink_callee,
            "sink_class": self.sink_class,
            "sink_file": self.sink_file,
            "sink_line": self.sink_line,
            "path": [
                {
                    "qualname": h.qualname,
                    "file": h.file,
                    "line": h.line,
                    "edge_kind": h.edge_kind,
                }
                for h in self.path
            ],
            "severity": self.severity,
            "confidence": self.confidence,
            "sanitized": self.sanitized,
        }


# ---------------------------------------------------------------------------
# Internal types
# ---------------------------------------------------------------------------

# A taint token: the node id being tracked, the cleared sink classes (cleared
# by sanitizers traversed so far), the confidence multiplier, and a pointer
# back to the parent token for path reconstruction.
@dataclass
class _TaintToken:
    node_id: str
    source_qualname: str
    source_class: str
    cleared_classes: frozenset[str]
    confidence: float
    parent: _TaintToken | None = field(default=None, repr=False, compare=False)
    parent_edge_kind: str = ""


# ---------------------------------------------------------------------------
# Graph helpers
# ---------------------------------------------------------------------------


def _node_attrs(graph: nx.MultiDiGraph, node_id: str) -> dict[str, Any]:
    """Return node attribute dict, or empty dict for sentinel / missing nodes."""
    if node_id not in graph:
        return {}
    return dict(graph.nodes[node_id])


def _node_qualname(graph: nx.MultiDiGraph, node_id: str) -> str:
    attrs = _node_attrs(graph, node_id)
    qn = str(attrs.get("qualname") or node_id)
    return qn


def _node_file(graph: nx.MultiDiGraph, node_id: str) -> str:
    return str(_node_attrs(graph, node_id).get("file") or "")


def _node_line(graph: nx.MultiDiGraph, node_id: str) -> int:
    return int(_node_attrs(graph, node_id).get("line_start") or 0)


def _node_kind(graph: nx.MultiDiGraph, node_id: str) -> str:
    return str(_node_attrs(graph, node_id).get("kind") or "")


def _out_edges_by_kind(
    graph: nx.MultiDiGraph, node_id: str, *kinds: str
) -> list[tuple[str, dict[str, Any]]]:
    """Return [(dst, full_edge_data)] for outgoing edges with any of *kinds*.

    The returned dict is a merge of top-level edge attrs and the nested
    ``metadata`` dict so callers can read ``file``, ``line`` (top-level) as
    well as ``callee``, ``position`` etc. (in metadata) from one dict.
    """
    result: list[tuple[str, dict[str, Any]]] = []
    if node_id not in graph:
        return result
    for _src, dst, key, edata in graph.out_edges(node_id, keys=True, data=True):
        if key in kinds:
            # Merge: start with the nested metadata, overlay top-level attrs.
            meta = dict(edata.get("metadata") or {})
            # Top-level file/line come from the Edge model fields directly.
            if edata.get("file"):
                meta.setdefault("file", edata["file"])
            if edata.get("line"):
                meta.setdefault("line", edata["line"])
            result.append((str(dst), meta))
    return result


def _in_edges_by_kind(
    graph: nx.MultiDiGraph, node_id: str, *kinds: str
) -> list[tuple[str, dict[str, Any]]]:
    """Return [(src, full_edge_data)] for incoming edges with any of *kinds*."""
    result: list[tuple[str, dict[str, Any]]] = []
    if node_id not in graph:
        return result
    for src, _dst, key, edata in graph.in_edges(node_id, keys=True, data=True):
        if key in kinds:
            meta = dict(edata.get("metadata") or {})
            if edata.get("file"):
                meta.setdefault("file", edata["file"])
            if edata.get("line"):
                meta.setdefault("line", edata["line"])
            result.append((str(src), meta))
    return result


# ---------------------------------------------------------------------------
# Seed collection
# ---------------------------------------------------------------------------

_UNRESOLVED_RET_RE = re.compile(r"^unresolved::ret::(.+)$")


def _collect_route_handler_ids(graph: nx.MultiDiGraph) -> set[str]:
    """Return the set of node IDs for functions that have an incoming ROUTE edge."""
    # ROUTE edges go FROM the function node TO a synthetic route:: target.
    handler_ids: set[str] = set()
    for src, _dst, key in graph.edges(keys=True):
        if key == EdgeKind.ROUTE.value:
            handler_ids.add(str(src))
    return handler_ids


def _collect_seeds(
    graph: nx.MultiDiGraph,
    catalog: TaintCatalog,
) -> list[_TaintToken]:
    """Build the initial worklist of taint tokens.

    Two seed kinds:
    1. PARAMETER nodes whose enclosing function has a ROUTE edge
       (route_param sources).
    2. VARIABLE nodes assigned from ``unresolved::ret::<callee>`` where the
       callee matches a call_result source regex.
    """
    seeds: list[_TaintToken] = []
    route_handler_ids = _collect_route_handler_ids(graph)

    for node_id, attrs in graph.nodes(data=True):
        kind = str(attrs.get("kind") or "")

        # --- Route-param seeds -------------------------------------------------
        if kind == NodeKind.PARAMETER.value:
            # The PARAMETER node has a PARAM_OF edge pointing to its function.
            for func_id, _meta in _out_edges_by_kind(
                graph, node_id, EdgeKind.PARAM_OF.value
            ):
                if func_id in route_handler_ids:
                    seeds.append(_TaintToken(
                        node_id=node_id,
                        source_qualname=str(attrs.get("qualname") or node_id),
                        source_class="http_request",
                        cleared_classes=frozenset(),
                        confidence=1.0,
                    ))
                    break  # One seed per param; don't duplicate.

        # --- Call-result seeds -------------------------------------------------
        elif kind == NodeKind.VARIABLE.value:
            # Look for an incoming DATA_ASSIGN from unresolved::ret::<callee>.
            for src_id, meta in _in_edges_by_kind(
                graph, node_id, EdgeKind.DATA_ASSIGN.value
            ):
                callee_text = str(meta.get("callee") or src_id)
                # Normalize: strip the sentinel prefix if present.
                m = _UNRESOLVED_RET_RE.match(src_id)
                if m:
                    callee_text = m.group(1)
                if not callee_text:
                    callee_text = str(meta.get("callee") or "")
                if not callee_text:
                    continue
                spec = _find_source_for_callee(catalog, callee_text)
                if spec is not None:
                    seeds.append(_TaintToken(
                        node_id=node_id,
                        source_qualname=str(attrs.get("qualname") or node_id),
                        source_class=spec.class_label,
                        cleared_classes=frozenset(),
                        confidence=1.0,
                    ))
                    break  # One seed per variable, first matching source.

    return seeds


def _find_source_for_callee(
    catalog: TaintCatalog, callee_text: str
) -> SourceSpec | None:
    """Match a callee text against call_result sources."""
    for spec in catalog.call_result_sources():
        if spec.matches(callee_text):
            return spec
    return None


# ---------------------------------------------------------------------------
# Inter-procedural bridge
# ---------------------------------------------------------------------------


def _callee_text_from_sentinel(sentinel_id: str, meta: dict[str, Any]) -> str:
    """Extract callee text from a DATA_ARG sentinel node id or edge metadata."""
    # Sentinel ID format: ``unresolved::arg::<callee>::<position|kwarg>``
    if sentinel_id.startswith("unresolved::arg::"):
        parts = sentinel_id.split("::", 3)
        if len(parts) >= 3:
            return parts[2]
    # Fall back to edge metadata.
    return str(meta.get("callee") or "")


def _resolve_callee_param_node(
    graph: nx.MultiDiGraph,
    caller_node_id: str,
    data_arg_dst: str,
    data_arg_meta: dict[str, Any],
) -> tuple[str | None, float]:
    """Try to resolve a DATA_ARG sentinel to a callee PARAMETER node.

    Returns ``(parameter_node_id, confidence_multiplier)`` or
    ``(None, 1.0)`` when no resolution is possible.

    Resolution strategy (in order):
    1. Find outgoing CALLS edges from any function that contains (DEFINED_IN)
       the ``caller_node_id`` node, whose callee qualname tail-matches the
       callee text and whose line number matches the DATA_ARG edge line.
       Confidence: 0.8 (tail-match).
    2. If that fails, search all PARAMETER nodes whose enclosing function
       qualname tail-matches the callee text and whose param index or name
       matches the DATA_ARG position/kwarg.
       Confidence: 0.8 x 0.9 = 0.72 if no name match.
    """
    callee_text = _callee_text_from_sentinel(data_arg_dst, data_arg_meta)
    if not callee_text:
        return None, 1.0

    position = data_arg_meta.get("position")
    kwarg = data_arg_meta.get("kwarg")
    arg_line = data_arg_meta.get("line")

    # Step 1: Walk CALLS edges from the caller's enclosing function(s).
    # The caller_node_id might be a VARIABLE or PARAMETER; find its function.
    enclosing_func_ids = _get_enclosing_function_ids(graph, caller_node_id)

    for func_id in enclosing_func_ids:
        for callee_id, calls_meta in _out_edges_by_kind(
            graph, func_id, EdgeKind.CALLS.value
        ):
            callee_qn = _node_qualname(graph, callee_id)
            # Tail-match: callee text should match the qualname suffix.
            if not _tail_matches(callee_qn, callee_text):
                continue
            # Optionally check call_line match if recorded.
            if arg_line is not None:
                call_line = calls_meta.get("call_line") or calls_meta.get("line")
                if call_line is not None and abs(int(call_line) - int(arg_line)) > 2:
                    continue
            # Found a resolved callee; now find the matching PARAMETER node.
            param_id, conf_mult = _find_param_in_callee(
                graph, callee_id, callee_qn, position, kwarg
            )
            if param_id is not None:
                return param_id, 0.8 * conf_mult

    # Step 2: Fall back to scanning all PARAMETER nodes for a qualname tail-match.
    for node_id, attrs in graph.nodes(data=True):
        if str(attrs.get("kind") or "") != NodeKind.PARAMETER.value:
            continue
        param_qn = str(attrs.get("qualname") or "")
        # qualname format: "<func_qualname>.<param:name>"
        if ".<param:" not in param_qn:
            continue
        func_part, param_part = param_qn.rsplit(".<param:", 1)
        param_name = param_part.rstrip(">")
        if not _tail_matches(func_part, callee_text):
            continue
        # Check position/name match.
        index = int(attrs.get("metadata", {}).get("index") or -1)
        if kwarg is not None and kwarg == param_name:
            return node_id, 0.8
        if position is not None and index == position:
            # Name not confirmed -- apply extra x0.9 penalty.
            return node_id, 0.8 * 0.9

    return None, 1.0


def _get_enclosing_function_ids(
    graph: nx.MultiDiGraph, node_id: str
) -> list[str]:
    """Return function/method node IDs that enclose (DEFINED_IN) *node_id*."""
    results: list[str] = []
    for dst, _meta in _out_edges_by_kind(graph, node_id, EdgeKind.DEFINED_IN.value):
        kind = _node_kind(graph, dst)
        if kind in (NodeKind.FUNCTION.value, NodeKind.METHOD.value):
            results.append(dst)
        else:
            # Keep walking up (e.g. variable defined in function defined in module).
            for dst2, _m in _out_edges_by_kind(graph, dst, EdgeKind.DEFINED_IN.value):
                k2 = _node_kind(graph, dst2)
                if k2 in (NodeKind.FUNCTION.value, NodeKind.METHOD.value):
                    results.append(dst2)
    return results


def _find_param_in_callee(
    graph: nx.MultiDiGraph,
    callee_id: str,
    callee_qn: str,
    position: int | None,
    kwarg: str | None,
) -> tuple[str | None, float]:
    """Find the PARAMETER node in *callee_id* matching *position* or *kwarg*."""
    # PARAMETER nodes have PARAM_OF edges pointing to the function.
    for param_id, attrs in graph.nodes(data=True):
        if str(attrs.get("kind") or "") != NodeKind.PARAMETER.value:
            continue
        for func_id, _meta in _out_edges_by_kind(
            graph, param_id, EdgeKind.PARAM_OF.value
        ):
            if func_id != callee_id:
                continue
            meta = attrs.get("metadata") or {}
            if not isinstance(meta, dict):
                continue
            index = meta.get("index")
            name = str(meta.get("name") or "")
            if kwarg is not None and kwarg == name:
                return param_id, 1.0
            if position is not None and index == position:
                # Position matched — check name for extra confidence.
                conf = 1.0 if (kwarg and kwarg == name) else 0.9
                return param_id, conf
    return None, 1.0


def _tail_matches(qualname: str, callee_text: str) -> bool:
    """Return True if *callee_text* matches the tail of *qualname*.

    Examples:
      ``sample.requests.get`` tail-matches ``requests.get``.
      ``f``                   tail-matches ``f``.
    """
    if not callee_text or not qualname:
        return False
    if qualname == callee_text:
        return True
    # The callee_text may use attribute access like "requests.get".
    # Qualname segments are dot-separated.
    if qualname.endswith("." + callee_text):
        return True
    # Last segment only match (e.g. callee "get" matches "sample.requests.get").
    qn_tail = qualname.rsplit(".", 1)[-1]
    return qn_tail == callee_text.rsplit(".", 1)[-1] and len(callee_text) > 1


def _find_call_result_vars(
    graph: nx.MultiDiGraph,
    callee_text: str,
    tainted_arg_node_id: str,
) -> list[str]:
    """Return VARIABLE nodes assigned from ``unresolved::ret::<callee_text>``.

    These represent the return value of a call to *callee_text*.  When a
    tainted argument flows into an external/unresolvable call, the call's
    result variable is also considered tainted (call-through propagation).

    We restrict to variables in the same enclosing function as the tainted
    argument to avoid false-positive pollution across unrelated functions.
    """
    # Get the enclosing function(s) of the tainted arg.
    enclosing_func_ids = set(_get_enclosing_function_ids(graph, tainted_arg_node_id))

    # Also accept sentinel sentinel nodes as source.
    # The sentinel format is unresolved::ret::<callee>.
    # Look for VARIABLE nodes whose incoming DATA_ASSIGN has callee == callee_text.
    results: list[str] = []
    for var_id, attrs in graph.nodes(data=True):
        if str(attrs.get("kind") or "") != NodeKind.VARIABLE.value:
            continue
        # Check that this variable is in the same function scope.
        var_func_ids = set(_get_enclosing_function_ids(graph, var_id))
        if enclosing_func_ids and not (var_func_ids & enclosing_func_ids):
            continue
        # Check for an incoming DATA_ASSIGN from unresolved::ret::<callee>.
        for src_id, meta in _in_edges_by_kind(
            graph, var_id, EdgeKind.DATA_ASSIGN.value
        ):
            callee_in_meta = str(meta.get("callee") or "")
            m = _UNRESOLVED_RET_RE.match(src_id)
            if m:
                callee_in_meta = m.group(1)
            if callee_in_meta and _tail_matches_callee(callee_in_meta, callee_text):
                results.append(var_id)
                break
    return results


def _tail_matches_callee(callee_in_graph: str, callee_text: str) -> bool:
    """Check whether two callee text strings refer to the same function.

    Handles cases like ``requests.get`` == ``requests.get`` and
    ``shlex.quote`` == ``shlex.quote``.
    """
    if callee_in_graph == callee_text:
        return True
    # Tail comparison — last segment must match.
    tail_g = callee_in_graph.rsplit(".", 1)[-1]
    tail_t = callee_text.rsplit(".", 1)[-1]
    return bool(tail_g and tail_t and tail_g == tail_t and len(callee_text) > 1)


# ---------------------------------------------------------------------------
# Sanitizer tracking
# ---------------------------------------------------------------------------


def _compute_cleared_classes(
    graph: nx.MultiDiGraph,
    node_id: str,
    catalog: TaintCatalog,
    existing_cleared: frozenset[str],
) -> frozenset[str]:
    """Return the updated cleared-class set after checking if *node_id* is a
    VARIABLE assigned from a sanitizer call.

    If the node was assigned from ``unresolved::ret::<callee>`` and the callee
    matches a sanitizer, add that sanitizer's ``clears`` to the set.
    """
    for src_id, meta in _in_edges_by_kind(
        graph, node_id, EdgeKind.DATA_ASSIGN.value
    ):
        callee_text = str(meta.get("callee") or "")
        m = _UNRESOLVED_RET_RE.match(src_id)
        if m:
            callee_text = m.group(1)
        if not callee_text:
            continue
        for san in catalog.find_sanitizers(callee_text):
            existing_cleared = existing_cleared | frozenset(san.clears)
    return existing_cleared


# ---------------------------------------------------------------------------
# Path reconstruction
# ---------------------------------------------------------------------------


def _reconstruct_path(
    graph: nx.MultiDiGraph, token: _TaintToken
) -> list[TaintHop]:
    """Walk the parent chain of *token* to build an ordered witness path."""
    hops: list[TaintHop] = []
    cur: _TaintToken | None = token
    while cur is not None:
        qn = _node_qualname(graph, cur.node_id)
        f = _node_file(graph, cur.node_id)
        ln = _node_line(graph, cur.node_id)
        hops.append(TaintHop(qualname=qn, file=f, line=ln, edge_kind=cur.parent_edge_kind))
        cur = cur.parent
    hops.reverse()
    return hops


# ---------------------------------------------------------------------------
# Main propagation
# ---------------------------------------------------------------------------


def propagate(
    graph: nx.MultiDiGraph,
    catalog: TaintCatalog,
    *,
    max_depth: int = 6,
) -> list[TaintFinding]:
    """Propagate taint through the graph and return all findings.

    Algorithm:
    1. Seed the worklist with route-param sources and call-result sources.
    2. For each token, follow DATA_ASSIGN and DATA_RETURN edges (node → node).
    3. For DATA_ARG edges, attempt inter-procedural resolution to the callee's
       PARAMETER node.  On success, enqueue the callee param with reduced
       confidence.
    4. At each node, check if it flows into a sink (DATA_ARG whose sentinel
       callee matches a SinkSpec).  If the cleared set covers the sink class,
       suppress the finding.
    5. Visited state is ``(node_id, cleared_classes)`` to allow re-visiting
       nodes with different sanitizer histories.
    6. Depth cap at ``max_depth`` prevents runaway traversal and cycle loops.

    Returns a deduplicated list of :class:`TaintFinding` objects.
    """
    seeds = _collect_seeds(graph, catalog)
    if not seeds:
        return []

    findings: list[TaintFinding] = []
    # Deduplication key: (source_qualname, sink_callee, sink_file, sink_line)
    seen_findings: set[tuple[str, str, str, int]] = set()

    for seed in seeds:
        _propagate_from_seed(
            graph, catalog, seed, max_depth, findings, seen_findings
        )

    return findings


def _propagate_from_seed(
    graph: nx.MultiDiGraph,
    catalog: TaintCatalog,
    seed: _TaintToken,
    max_depth: int,
    findings: list[TaintFinding],
    seen_findings: set[tuple[str, str, str, int]],
) -> None:
    """BFS propagation from a single seed token."""
    # Visited: (node_id, cleared_classes_frozen)
    visited: set[tuple[str, frozenset[str]]] = set()

    queue: deque[tuple[_TaintToken, int]] = deque()
    queue.append((seed, 0))

    while queue:
        token, depth = queue.popleft()

        visit_key = (token.node_id, token.cleared_classes)
        if visit_key in visited:
            continue
        visited.add(visit_key)

        if depth >= max_depth:
            continue

        # ----------------------------------------------------------------
        # Check for sanitizer: if this node is a call result of a sanitizer,
        # update cleared_classes.
        # ----------------------------------------------------------------
        new_cleared = _compute_cleared_classes(
            graph, token.node_id, catalog, token.cleared_classes
        )
        if new_cleared != token.cleared_classes:
            # Rebuild token with updated cleared set.
            token = _TaintToken(
                node_id=token.node_id,
                source_qualname=token.source_qualname,
                source_class=token.source_class,
                cleared_classes=new_cleared,
                confidence=token.confidence,
                parent=token.parent,
                parent_edge_kind=token.parent_edge_kind,
            )

        # ----------------------------------------------------------------
        # Check for sink: outgoing DATA_ARG edges whose sentinel callee
        # matches a SinkSpec.
        # ----------------------------------------------------------------
        for arg_dst, arg_meta in _out_edges_by_kind(
            graph, token.node_id, EdgeKind.DATA_ARG.value
        ):
            callee_text = _callee_text_from_sentinel(arg_dst, arg_meta)
            if not callee_text:
                continue
            sink_spec = catalog.find_sink(callee_text)
            if sink_spec is None:
                continue

            # Check arg position restriction.
            position = arg_meta.get("position")
            if not sink_spec.position_is_dangerous(
                int(position) if position is not None else None
            ):
                continue

            # Check sanitizer coverage.
            if sink_spec.class_label in token.cleared_classes:
                # Taint has been sanitized for this sink class — suppress.
                continue

            # Find file/line from the DATA_ARG edge metadata or sentinel node.
            sink_file = str(arg_meta.get("file") or _node_file(graph, arg_dst))
            sink_line_raw = arg_meta.get("line") or _node_line(graph, arg_dst)
            sink_line = int(sink_line_raw) if sink_line_raw else 0

            # Deduplicate findings.
            fkey = (
                token.source_qualname,
                callee_text,
                sink_file,
                sink_line,
            )
            if fkey in seen_findings:
                continue
            seen_findings.add(fkey)

            path = _reconstruct_path(graph, token)
            findings.append(TaintFinding(
                source_qualname=token.source_qualname,
                source_class=token.source_class,
                sink_callee=callee_text,
                sink_class=sink_spec.class_label,
                sink_file=sink_file,
                sink_line=sink_line,
                path=path,
                severity=sink_spec.severity,
                confidence=round(token.confidence, 4),
                sanitized=False,
            ))

        # ----------------------------------------------------------------
        # Forward propagation over DATA_ASSIGN and DATA_RETURN edges.
        # These carry taint node-to-node.
        # ----------------------------------------------------------------
        for dst, _meta in _out_edges_by_kind(
            graph, token.node_id,
            EdgeKind.DATA_ASSIGN.value,
            EdgeKind.DATA_RETURN.value,
        ):
            # Skip sentinel nodes — they are not real nodes to propagate into.
            if dst.startswith("unresolved::"):
                continue
            next_key = (dst, token.cleared_classes)
            if next_key in visited:
                continue
            child = _TaintToken(
                node_id=dst,
                source_qualname=token.source_qualname,
                source_class=token.source_class,
                cleared_classes=token.cleared_classes,
                confidence=token.confidence,
                parent=token,
                parent_edge_kind=EdgeKind.DATA_ASSIGN.value,
            )
            queue.append((child, depth + 1))

        # ----------------------------------------------------------------
        # Inter-procedural hop: DATA_ARG edges whose sentinel can be resolved
        # to a callee PARAMETER node.
        #
        # Additionally, "call-through propagation": when a tainted value is
        # passed to an UNRESOLVABLE call (external library / stdlib), the
        # call's return value may also be tainted.  We look for VARIABLE nodes
        # assigned from ``unresolved::ret::<callee>`` whose callee matches the
        # DATA_ARG callee text — these represent the result of the same call.
        # Confidence is reduced by x0.8 for this unverified passthrough.
        # ----------------------------------------------------------------
        for arg_dst, arg_meta in _out_edges_by_kind(
            graph, token.node_id, EdgeKind.DATA_ARG.value
        ):
            callee_text_arg = _callee_text_from_sentinel(arg_dst, arg_meta)

            # Attempt inter-procedural resolution first (in-graph callees).
            param_id, conf_mult = _resolve_callee_param_node(
                graph, token.node_id, arg_dst, arg_meta
            )
            if param_id is not None:
                next_key = (param_id, token.cleared_classes)
                if next_key not in visited:
                    child = _TaintToken(
                        node_id=param_id,
                        source_qualname=token.source_qualname,
                        source_class=token.source_class,
                        cleared_classes=token.cleared_classes,
                        confidence=token.confidence * conf_mult,
                        parent=token,
                        parent_edge_kind=EdgeKind.DATA_ARG.value,
                    )
                    queue.append((child, depth + 1))

            # Call-through: find the return variable of this same callee.
            # When the callee is unresolvable (no in-graph parameter node found),
            # taint the call result variable so taint flows through external calls.
            # The sanitizer check on that variable happens in the next BFS step.
            if callee_text_arg:
                for ret_var_id in _find_call_result_vars(
                    graph, callee_text_arg, token.node_id
                ):
                    next_key = (ret_var_id, token.cleared_classes)
                    if next_key in visited:
                        continue
                    child = _TaintToken(
                        node_id=ret_var_id,
                        source_qualname=token.source_qualname,
                        source_class=token.source_class,
                        cleared_classes=token.cleared_classes,
                        # Slight confidence reduction for unverified call-through.
                        confidence=token.confidence * 0.9,
                        parent=token,
                        parent_edge_kind=EdgeKind.DATA_ARG.value,
                    )
                    queue.append((child, depth + 1))


__all__ = [
    "TaintFinding",
    "TaintHop",
    "propagate",
]
