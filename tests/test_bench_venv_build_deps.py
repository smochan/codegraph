"""Tests for `ensure_venv` build_deps support (v0.1.2 #11).

The repomapper bench runner installs `aider-chat`, which on Python 3.14
fails because the bundled pip doesn't provision `setuptools.build_meta`
fast enough. `ensure_venv(..., build_deps=[...])` installs the build-time
deps in a separate `pip install` call before the main one, so the build
backend is fully resolved when aider's wheel is built.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from bench.runners._venv import ensure_venv


def test_build_deps_installed_before_pip_install(tmp_path: Path, monkeypatch) -> None:
    """`build_deps` must run as its own pip install BEFORE pip_install."""
    monkeypatch.chdir(tmp_path)

    calls: list[list[str]] = []

    def fake_run(argv, *args, **kwargs):
        calls.append(list(argv))
        # Create the expected files so the function continues past its checks.
        if argv[1:3] == ["-m", "venv"]:
            venv_dir = Path(argv[3])
            (venv_dir / "bin").mkdir(parents=True, exist_ok=True)
        return type("R", (), {"returncode": 0})()

    with patch("bench.runners._venv.subprocess.run", side_effect=fake_run):
        ensure_venv("repomapper", build_deps=["setuptools", "wheel"], pip_install=["aider-chat"])

    pip_invocations = [
        c for c in calls if any("pip" in part for part in c) and "install" in c
    ]
    # Expect: pip upgrade, then build_deps install, then pip_install.
    assert len(pip_invocations) == 3
    assert pip_invocations[0][-2:] == ["--upgrade", "pip"]
    assert "setuptools" in pip_invocations[1]
    assert "wheel" in pip_invocations[1]
    assert "aider-chat" in pip_invocations[2]
    # build_deps install MUST come before the aider install.
    assert calls.index(pip_invocations[1]) < calls.index(pip_invocations[2])


def test_build_deps_optional(tmp_path: Path, monkeypatch) -> None:
    """When build_deps is None/empty, only the regular pip_install runs."""
    monkeypatch.chdir(tmp_path)

    calls: list[list[str]] = []

    def fake_run(argv, *args, **kwargs):
        calls.append(list(argv))
        if argv[1:3] == ["-m", "venv"]:
            venv_dir = Path(argv[3])
            (venv_dir / "bin").mkdir(parents=True, exist_ok=True)
        return type("R", (), {"returncode": 0})()

    with patch("bench.runners._venv.subprocess.run", side_effect=fake_run):
        ensure_venv("foo", pip_install=["somepkg"])

    install_calls = [c for c in calls if "install" in c]
    # Just: pip upgrade + pip_install. No build_deps in the middle.
    assert len(install_calls) == 2
    assert "somepkg" in install_calls[1]
