"""Git hook installation for ``codegraph review`` integration."""
from __future__ import annotations

import stat
from pathlib import Path

HOOK_MARKER = "# codegraph-managed-hook"

DEFAULT_HOOK_NAME = "pre-push"


def _hook_script(target: str = "main") -> str:
    return f"""#!/usr/bin/env bash
{HOOK_MARKER}
# Runs codegraph review against the configured baseline.
set -e
if ! command -v codegraph >/dev/null 2>&1; then
    echo "codegraph: skipping (CLI not on PATH)"
    exit 0
fi
codegraph review --target {target} --fail-on high || exit $?
"""


def _hooks_dir(repo_root: Path) -> Path:
    return repo_root / ".git" / "hooks"


def install_hook(
    repo_root: Path,
    hook: str = DEFAULT_HOOK_NAME,
    target: str = "main",
    force: bool = False,
) -> Path:
    """Install a codegraph-managed git hook in ``repo_root``.

    Returns the path of the installed hook. Raises ``FileExistsError`` if a
    foreign (non-codegraph) hook is already present and ``force`` is False.
    """
    hooks_dir = _hooks_dir(repo_root)
    if not hooks_dir.parent.exists():
        raise FileNotFoundError(f"not a git repository: {repo_root}")
    hooks_dir.mkdir(parents=True, exist_ok=True)
    hook_path = hooks_dir / hook
    if hook_path.exists() and not force:
        existing = hook_path.read_text()
        if HOOK_MARKER not in existing:
            raise FileExistsError(
                f"refusing to overwrite existing {hook} hook (use --force)"
            )
    hook_path.write_text(_hook_script(target=target))
    mode = hook_path.stat().st_mode
    hook_path.chmod(mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return hook_path


def uninstall_hook(
    repo_root: Path, hook: str = DEFAULT_HOOK_NAME
) -> bool:
    """Remove a codegraph-managed git hook. Returns True if removed."""
    hook_path = _hooks_dir(repo_root) / hook
    if not hook_path.exists():
        return False
    text = hook_path.read_text()
    if HOOK_MARKER not in text:
        return False
    hook_path.unlink()
    return True


def is_installed(repo_root: Path, hook: str = DEFAULT_HOOK_NAME) -> bool:
    hook_path = _hooks_dir(repo_root) / hook
    if not hook_path.exists():
        return False
    return HOOK_MARKER in hook_path.read_text()
