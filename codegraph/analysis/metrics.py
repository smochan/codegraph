"""Aggregate graph metrics."""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

import networkx as nx

from codegraph.analysis._common import _kind_str


@dataclass
class GraphMetrics:
    total_nodes: int = 0
    total_edges: int = 0
    nodes_by_kind: dict[str, int] = field(default_factory=dict)
    edges_by_kind: dict[str, int] = field(default_factory=dict)
    languages: dict[str, int] = field(default_factory=dict)
    top_files_by_nodes: list[tuple[str, int]] = field(default_factory=list)
    # Total of `external_edges + unresolved_local_edges`. Kept for back-compat
    # with consumers that pre-date the 0.1.2 split.
    unresolved_edges: int = 0
    # Imports whose root module is not part of this repo (e.g. `fastapi`,
    # `os`, `react`). These are expected, not errors — they're cross-boundary
    # references that static analysis without a venv / site-packages parse
    # cannot resolve and isn't supposed to.
    external_edges: int = 0
    # Unresolved edges whose root module IS in the repo but couldn't be
    # matched (rename drift, dynamic import, missed binding). These are the
    # actionable ones.
    unresolved_local_edges: int = 0


_UNRESOLVED_PREFIX = "unresolved::"


def _module_root(qualname: str) -> str:
    """First segment of a dotted qualname, e.g. ``foo.bar.baz`` -> ``foo``.

    Also handles TS path-style names (``pkg/sub/file``) and rare ``a::b``
    forms by stripping at the first separator of any flavour.
    """
    if not qualname:
        return ""
    head = qualname.split(".", 1)[0]
    for sep in ("/", "::"):
        if sep in head:
            head = head.split(sep, 1)[0]
    return head


def _collect_repo_roots(graph: nx.MultiDiGraph) -> set[str]:
    """Module-name roots that live in the repo.

    Used to classify each unresolved edge as either ``external`` (root not
    in the repo — e.g. ``fastapi``, ``os``) or ``unresolved_local`` (root
    is a repo package but the specific symbol couldn't be matched).
    """
    roots: set[str] = set()
    for _nid, attrs in graph.nodes(data=True):
        if _kind_str(attrs.get("kind")) != "MODULE":
            continue
        qn = attrs.get("qualname")
        if isinstance(qn, str):
            root = _module_root(qn)
            if root:
                roots.add(root)
    return roots


def compute_metrics(graph: nx.MultiDiGraph, *, top_files: int = 10) -> GraphMetrics:
    metrics = GraphMetrics(total_nodes=graph.number_of_nodes())
    kind_counter: Counter[str] = Counter()
    lang_counter: Counter[str] = Counter()
    file_counter: Counter[str] = Counter()
    for _nid, attrs in graph.nodes(data=True):
        kind = _kind_str(attrs.get("kind")) or "UNKNOWN"
        kind_counter[kind] += 1
        lang = str(attrs.get("language") or "unknown")
        lang_counter[lang] += 1
        file_path = attrs.get("file")
        if isinstance(file_path, str) and file_path:
            file_counter[file_path] += 1
    metrics.nodes_by_kind = dict(sorted(kind_counter.items()))
    metrics.languages = dict(sorted(lang_counter.items()))
    metrics.top_files_by_nodes = file_counter.most_common(top_files)

    repo_roots = _collect_repo_roots(graph)

    edge_counter: Counter[str] = Counter()
    external = 0
    unresolved_local = 0
    total = 0
    for _src, dst, _key, data in graph.edges(keys=True, data=True):
        total += 1
        ek = _kind_str(data.get("kind")) or "UNKNOWN"
        edge_counter[ek] += 1
        if isinstance(dst, str) and dst.startswith(_UNRESOLVED_PREFIX):
            target = dst[len(_UNRESOLVED_PREFIX):]
            root = _module_root(target)
            if root and root in repo_roots:
                unresolved_local += 1
            else:
                external += 1
    metrics.total_edges = total
    metrics.edges_by_kind = dict(sorted(edge_counter.items()))
    metrics.external_edges = external
    metrics.unresolved_local_edges = unresolved_local
    metrics.unresolved_edges = external + unresolved_local
    return metrics
