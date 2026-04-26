"""Codegraph configuration model and helpers."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field


class DeadCodeConfig(BaseModel):
    """User-supplied dead-code analysis tweaks.

    Extends the built-in entry-point catalog. All fields are optional;
    user patterns are merged with the built-ins at parse time.
    """

    entry_point_decorators: list[str] = Field(default_factory=list)
    """Extra decorator strings (e.g. ``"@my.handler"``) treated as entry
    points. Matched as substring of the raw decorator text."""

    entry_point_names: list[str] = Field(default_factory=list)
    """Extra function/method/class name globs treated as entry points
    (fnmatch syntax). Reserved for future use."""

    entry_point_files: list[str] = Field(default_factory=list)
    """File-path globs whose definitions are all treated as entry points.
    Reserved for future use."""


class CodegraphConfig(BaseModel):
    version: int = 1
    languages: list[str] = Field(
        default_factory=lambda: ["python", "typescript", "javascript"]
    )
    default_branch: str = "main"
    ignore: list[str] = Field(default_factory=list)
    baseline: dict[str, Any] = Field(
        default_factory=lambda: {"backend": "local"}
    )
    critical_paths: list[dict[str, Any]] = Field(default_factory=list)
    mcp: dict[str, Any] = Field(default_factory=lambda: {"enabled": False})
    install_hook: bool = False
    register_mcp: bool = False
    dead_code: DeadCodeConfig = Field(default_factory=DeadCodeConfig)


def load_config(repo_root: Path) -> CodegraphConfig:
    cfg_path = repo_root / ".codegraph.yml"
    if not cfg_path.exists():
        return CodegraphConfig()
    with cfg_path.open() as f:
        data = yaml.safe_load(f) or {}
    return CodegraphConfig.model_validate(data)


def save_config(repo_root: Path, cfg: CodegraphConfig) -> None:
    cfg_path = repo_root / ".codegraph.yml"
    with cfg_path.open("w") as f:
        yaml.dump(cfg.model_dump(), f, default_flow_style=False, sort_keys=True)


def default_data_dir(repo_root: Path) -> Path:
    return repo_root / ".codegraph"
