"""Cross-repo workspace mode for codegraph.

A *workspace* is a user-level registration of N independent repositories that
codegraph should treat as a single mental unit for cross-repo queries. Each
registered repo still keeps its own ``.codegraph/graph.db``; workspace
operations open them in parallel and union/aggregate the results.

Public API:
    - :class:`codegraph.workspace.config.WorkspaceConfig`
    - :func:`codegraph.workspace.config.load_workspace`
    - :func:`codegraph.workspace.config.save_workspace`
    - :func:`codegraph.workspace.operations.workspace_state`
    - :func:`codegraph.workspace.operations.workspace_diff_since`
    - :func:`codegraph.workspace.operations.workspace_blast_radius`
"""
from __future__ import annotations

from codegraph.workspace.config import (
    USER_WORKSPACE_FILE,
    WorkspaceConfig,
    WorkspaceRepo,
    load_workspace,
    resolve_workspace_path,
    save_workspace,
)

__all__ = [
    "USER_WORKSPACE_FILE",
    "WorkspaceConfig",
    "WorkspaceRepo",
    "load_workspace",
    "resolve_workspace_path",
    "save_workspace",
]
