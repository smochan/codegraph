"""Per-tool isolated venv helper.

Each external tool gets its own venv under bench/.venvs/<tool>/ to avoid
dependency collisions (e.g. tree-sitter-language-pack version pins that conflict
with polycodegraph's). The bench harness creates these on-demand via
`codegraph bench setup` and runners shell out to the venv's binary directly.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

VENVS_ROOT = Path("bench/.venvs")


def venv_dir(tool: str) -> Path:
    return VENVS_ROOT / tool


def venv_bin(tool: str, name: str) -> Path:
    """Return the absolute path to `<venv>/bin/<name>` (POSIX) for `tool`."""
    return (venv_dir(tool) / "bin" / name).resolve()


def ensure_venv(
    tool: str,
    *,
    pip_install: list[str],
    build_deps: list[str] | None = None,
    force: bool = False,
) -> Path:
    """Create the tool's venv and install the given packages if not present.

    Returns the venv directory. Safe to call repeatedly — fast-path checks the
    bin/<tool> binary exists before doing any work.

    *build_deps* are installed in a separate ``pip install`` call **before**
    ``pip_install``. Use this when a package in ``pip_install`` needs a build
    backend or setuptools shim that the bundled pip won't auto-provision —
    most notably ``aider-chat`` on Python 3.14, where the missing
    ``setuptools.build_meta`` import breaks installation unless setuptools
    is fully resolved up front.
    """
    vdir = venv_dir(tool)
    vdir.parent.mkdir(parents=True, exist_ok=True)
    bin_path = vdir / "bin" / tool
    if bin_path.exists() and not force:
        return vdir
    if force and vdir.exists():
        import shutil
        shutil.rmtree(vdir)
    subprocess.run([sys.executable, "-m", "venv", str(vdir)], check=True)
    subprocess.run(
        [str(vdir / "bin" / "pip"), "install", "--quiet", "--upgrade", "pip"],
        check=True,
    )
    if build_deps:
        subprocess.run(
            [str(vdir / "bin" / "pip"), "install", "--quiet", *build_deps],
            check=True,
        )
    if pip_install:
        subprocess.run(
            [str(vdir / "bin" / "pip"), "install", "--quiet", *pip_install],
            check=True,
        )
    return vdir
