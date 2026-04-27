"""Whole-project analyses operating on the codegraph store."""
from codegraph.analysis.blast_radius import BlastRadiusResult, blast_radius
from codegraph.analysis.cycles import Cycle, CycleReport, find_cycles
from codegraph.analysis.dataflow import DataFlow, FlowHop, match_route, trace
from codegraph.analysis.dead_code import DeadNode, find_dead_code
from codegraph.analysis.hotspots import Hotspot, find_hotspots
from codegraph.analysis.metrics import GraphMetrics, compute_metrics
from codegraph.analysis.roles import classify_roles
from codegraph.analysis.untested import UntestedNode, find_untested

__all__ = [
    "BlastRadiusResult",
    "Cycle",
    "CycleReport",
    "DataFlow",
    "DeadNode",
    "FlowHop",
    "GraphMetrics",
    "Hotspot",
    "UntestedNode",
    "blast_radius",
    "classify_roles",
    "compute_metrics",
    "find_cycles",
    "find_dead_code",
    "find_hotspots",
    "find_untested",
    "match_route",
    "trace",
]
