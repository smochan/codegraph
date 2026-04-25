"""Shared styling for codegraph visualizations."""
from __future__ import annotations

from codegraph.graph.schema import EdgeKind, NodeKind

KIND_COLOR: dict[str, str] = {
    NodeKind.FILE.value: "#94a3b8",      # slate
    NodeKind.MODULE.value: "#6366f1",    # indigo
    NodeKind.CLASS.value: "#f59e0b",     # amber
    NodeKind.FUNCTION.value: "#10b981",  # emerald
    NodeKind.METHOD.value: "#22c55e",    # green
    NodeKind.VARIABLE.value: "#9ca3af",  # gray
    NodeKind.PARAMETER.value: "#9ca3af",
    NodeKind.IMPORT.value: "#0ea5e9",    # sky
    NodeKind.TEST.value: "#ec4899",      # pink
}

KIND_CLASS: dict[str, str] = {
    NodeKind.FILE.value: "file",
    NodeKind.MODULE.value: "module",
    NodeKind.CLASS.value: "klass",
    NodeKind.FUNCTION.value: "func",
    NodeKind.METHOD.value: "method",
    NodeKind.VARIABLE.value: "var",
    NodeKind.PARAMETER.value: "param",
    NodeKind.IMPORT.value: "imp",
    NodeKind.TEST.value: "test",
}

EDGE_STYLE: dict[str, str] = {
    EdgeKind.DEFINED_IN.value: "dashed",
    EdgeKind.IMPORTS.value: "dotted",
    EdgeKind.CALLS.value: "solid",
    EdgeKind.INHERITS.value: "bold",
    EdgeKind.IMPLEMENTS.value: "bold",
    EdgeKind.READS.value: "dotted",
    EdgeKind.WRITES.value: "dotted",
    EdgeKind.RETURNS.value: "solid",
    EdgeKind.PARAM_OF.value: "dashed",
    EdgeKind.TESTED_BY.value: "dashed",
}


def kind_str(value: object) -> str:
    return str(getattr(value, "value", value) or "")
