"""Workspace configuration model + load/save helpers.

The workspace file lives at ``~/.codegraph/workspace.yml`` by default.
Override via the ``CODEGRAPH_WORKSPACE_FILE`` environment variable — useful
for tests and for users who want to isolate workspaces per shell.
"""
from __future__ import annotations

import os
from pathlib import Path

import yaml
from pydantic import BaseModel, Field

USER_WORKSPACE_FILE = Path.home() / ".codegraph" / "workspace.yml"
"""Default user-level workspace file location."""


class WorkspaceRepo(BaseModel):
    """A single repository registered in a workspace.

    Attributes:
        path: Absolute path to the repository root.
        name: Optional short label (defaults to ``Path(path).name`` when read).
    """

    path: str
    name: str | None = None

    @property
    def display_name(self) -> str:
        return self.name or Path(self.path).name


class WorkspaceConfig(BaseModel):
    """User-level workspace configuration.

    Stored as YAML at ``~/.codegraph/workspace.yml``::

        version: 1
        repos:
          - path: /Users/me/Documents/projects/foo
            name: foo
          - path: /Users/me/Documents/projects/bar
    """

    version: int = 1
    repos: list[WorkspaceRepo] = Field(default_factory=list)

    def has_repo(self, repo_path: str | Path) -> bool:
        target = str(Path(repo_path).expanduser().resolve())
        return any(str(Path(r.path).resolve()) == target for r in self.repos)

    def remove_repo(self, repo_path: str | Path) -> bool:
        """Drop the repo whose absolute path matches *repo_path*.

        Returns True if something was removed.
        """
        target = str(Path(repo_path).expanduser().resolve())
        before = len(self.repos)
        self.repos = [
            r for r in self.repos if str(Path(r.path).resolve()) != target
        ]
        return len(self.repos) != before


def resolve_workspace_path() -> Path:
    """Return the workspace file path, respecting the env override."""
    override = os.environ.get("CODEGRAPH_WORKSPACE_FILE")
    if override:
        return Path(override).expanduser()
    return USER_WORKSPACE_FILE


def load_workspace(path: Path | None = None) -> WorkspaceConfig:
    """Load the workspace from *path* (or the resolved default).

    Returns an empty :class:`WorkspaceConfig` if the file is missing; never raises
    for a missing file. Raises ``ValueError`` for malformed YAML or schema errors.
    """
    cfg_path = path or resolve_workspace_path()
    if not cfg_path.exists():
        return WorkspaceConfig()
    try:
        raw = cfg_path.read_text()
    except OSError as exc:
        raise ValueError(f"Cannot read workspace file at {cfg_path}: {exc}") from exc
    try:
        data = yaml.safe_load(raw) or {}
    except yaml.YAMLError as exc:
        raise ValueError(f"Invalid YAML in {cfg_path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError(
            f"Workspace file {cfg_path} must be a mapping, got {type(data).__name__}"
        )
    return WorkspaceConfig.model_validate(data)


def save_workspace(cfg: WorkspaceConfig, path: Path | None = None) -> Path:
    """Persist *cfg* to *path* (or the resolved default).

    Creates parent dirs as needed. Returns the path written to.
    """
    cfg_path = path or resolve_workspace_path()
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    payload = cfg.model_dump(mode="json")
    cfg_path.write_text(
        yaml.safe_dump(payload, sort_keys=False, default_flow_style=False)
    )
    return cfg_path
