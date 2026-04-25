"""Codegraph configuration model and helpers."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field


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
