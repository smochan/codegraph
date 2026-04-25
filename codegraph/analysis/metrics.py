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
    unresolved_edges: int = 0


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

    edge_counter: Counter[str] = Counter()
    unresolved = 0
    total = 0
    for _src, dst, _key, data in graph.edges(keys=True, data=True):
        total += 1
        ek = _kind_str(data.get("kind")) or "UNKNOWN"
        edge_counter[ek] += 1
        if isinstance(dst, str) and dst.startswith("unresolved::"):
            unresolved += 1
    metrics.total_edges = total
    metrics.edges_by_kind = dict(sorted(edge_counter.items()))
    metrics.unresolved_edges = unresolved
    return metrics
