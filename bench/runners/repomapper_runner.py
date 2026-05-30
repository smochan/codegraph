"""RepoMapper adapter — graph-only baseline.

Upstream: https://github.com/pdavis68/RepoMapper (MIT, Python, git-clone install only).
No PR-review surface. We run the mapper to produce the ranked repo map and
report setup time as a capability metric.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

from bench.runners._graph_only import GraphOnlyRunner
from bench.runners._venv import VENVS_ROOT, ensure_venv
from bench.types import CommitTarget

_REPO = "https://github.com/pdavis68/RepoMapper.git"


def _ensure_repomapper() -> Path:
    """RepoMapper is git-clone-only. Bring it into bench/.venvs/repomapper/src/."""
    venv = ensure_venv(
        "repomapper",
        # aider-chat's build backend imports `setuptools.build_meta` at
        # install time. On Python 3.14 the bundled pip does not auto-
        # provision setuptools quickly enough, so we install it (and
        # wheel, which aider's setup.py also reaches for) explicitly
        # first. Without this prelude, `pip install aider-chat` fails
        # with `ModuleNotFoundError: No module named 'setuptools.build_meta'`.
        build_deps=["setuptools", "wheel"],
        pip_install=["aider-chat"],  # repomap dep chain
    )
    src = (venv / "src").resolve()
    if not src.exists():
        src.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "clone", "--depth", "1", _REPO, str(src)], check=True)
        # Pip-install its requirements into the venv.
        req = src / "requirements.txt"
        if req.exists():
            subprocess.run(
                [str(venv / "bin" / "pip"), "install", "--quiet", "-r", str(req)],
                check=False,
            )
    return src


class RepoMapperRunner(GraphOnlyRunner):
    name = "repomapper"
    upstream_url = "https://github.com/pdavis68/RepoMapper"

    def build_argv(self, target: CommitTarget) -> list[str]:
        src = _ensure_repomapper()
        venv_py = (VENVS_ROOT / "repomapper" / "bin" / "python").resolve()
        # RepoMapper exposes a `repomap.py` script in the cloned repo root.
        script = src / "repomap.py"
        if not script.exists():
            # Fallback: some forks expose a `repomapper` console script.
            return [str(venv_py), "-m", "repomapper", str(target.repo_path)]
        return [
            str(venv_py), str(script),
            "--root", str(target.repo_path),
        ]
