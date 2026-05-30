"""Per-ecosystem ignore-pattern presets, auto-applied during `codegraph init`.

Replaces the free-text "Extra ignore patterns" prompt for common cases —
that prompt was a footgun: a user once typed "y" thinking it was yes/no
and ended up with ``ignore: [- y]`` in their YAML.
"""
from __future__ import annotations

import json
from pathlib import Path

# Each preset maps an ecosystem name to its canonical ignore patterns.
# Lookups are file-presence-based to keep detection cheap and robust.
_NODE_BASE: tuple[str, ...] = ("node_modules/", "dist/", "build/")
_NODE_RN: tuple[str, ...] = ("ios/Pods/", "android/build/", "android/.gradle/")
_PYTHON: tuple[str, ...] = (
    "__pycache__/", ".venv/", "venv/", ".tox/", ".pytest_cache/",
    ".mypy_cache/", ".ruff_cache/", "*.egg-info/",
)
_GO: tuple[str, ...] = ("vendor/",)
_RUST: tuple[str, ...] = ("target/",)
_JAVA_MAVEN: tuple[str, ...] = ("target/",)
_JAVA_GRADLE: tuple[str, ...] = ("build/", ".gradle/")


def _has_react_native(package_json: Path) -> bool:
    try:
        data = json.loads(package_json.read_text())
    except (OSError, ValueError):
        return False
    if not isinstance(data, dict):
        return False
    deps = data.get("dependencies") or {}
    dev_deps = data.get("devDependencies") or {}
    if not isinstance(deps, dict):
        deps = {}
    if not isinstance(dev_deps, dict):
        dev_deps = {}
    return "react-native" in deps or "react-native" in dev_deps


def detect_ignore_presets(repo_root: Path) -> tuple[list[str], list[str]]:
    """Return ``(patterns, ecosystem_labels)`` for what was detected.

    Patterns are de-duplicated in insertion order. Ecosystem labels are
    short human-readable tags (e.g. ``"python"``, ``"node"``,
    ``"react-native"``) used by the CLI for the "Auto-detected" line.
    """
    patterns: list[str] = []
    labels: list[str] = []
    seen: set[str] = set()

    def _add(items: tuple[str, ...]) -> None:
        for item in items:
            if item not in seen:
                seen.add(item)
                patterns.append(item)

    # Python
    if (
        (repo_root / "pyproject.toml").exists()
        or (repo_root / "requirements.txt").exists()
        or (repo_root / "setup.py").exists()
        or (repo_root / "setup.cfg").exists()
    ):
        labels.append("python")
        _add(_PYTHON)

    # Node / JS / TS
    package_json = repo_root / "package.json"
    if package_json.exists():
        labels.append("node")
        _add(_NODE_BASE)
        if _has_react_native(package_json):
            labels.append("react-native")
            _add(_NODE_RN)

    # Go
    if (repo_root / "go.mod").exists():
        labels.append("go")
        _add(_GO)

    # Rust
    if (repo_root / "Cargo.toml").exists():
        labels.append("rust")
        _add(_RUST)

    # Java
    if (repo_root / "pom.xml").exists():
        labels.append("java-maven")
        _add(_JAVA_MAVEN)
    if (
        (repo_root / "build.gradle").exists()
        or (repo_root / "build.gradle.kts").exists()
    ):
        labels.append("java-gradle")
        _add(_JAVA_GRADLE)

    return patterns, labels
