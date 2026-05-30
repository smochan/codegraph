"""Tests for `detect_ignore_presets` (v0.1.2 #5)."""
from __future__ import annotations

import json
from pathlib import Path

from codegraph.init_presets import detect_ignore_presets


def test_python_project(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n")
    patterns, labels = detect_ignore_presets(tmp_path)
    assert "python" in labels
    assert "__pycache__/" in patterns
    assert ".venv/" in patterns


def test_node_project(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text(json.dumps({"name": "x"}))
    patterns, labels = detect_ignore_presets(tmp_path)
    assert "node" in labels
    assert "node_modules/" in patterns
    # No RN-specific patterns when react-native isn't a dep.
    assert "ios/Pods/" not in patterns


def test_react_native_project(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text(json.dumps({
        "name": "rn-app",
        "dependencies": {"react-native": "0.74"},
    }))
    patterns, labels = detect_ignore_presets(tmp_path)
    assert "react-native" in labels
    assert "ios/Pods/" in patterns
    assert "android/build/" in patterns
    assert "node_modules/" in patterns


def test_go_project(tmp_path: Path) -> None:
    (tmp_path / "go.mod").write_text("module x\n")
    patterns, labels = detect_ignore_presets(tmp_path)
    assert "go" in labels
    assert "vendor/" in patterns


def test_multilang_project_dedupes(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text(json.dumps({"name": "x"}))
    (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n")
    (tmp_path / "pom.xml").write_text("<project/>")
    patterns, labels = detect_ignore_presets(tmp_path)
    assert "python" in labels
    assert "node" in labels
    assert "java-maven" in labels
    # `target/` could come from java-maven and rust; here only maven → present once
    assert patterns.count("target/") == 1


def test_empty_project_returns_empty(tmp_path: Path) -> None:
    patterns, labels = detect_ignore_presets(tmp_path)
    assert patterns == []
    assert labels == []


def test_malformed_package_json_doesnt_crash(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text("not json {{{")
    patterns, labels = detect_ignore_presets(tmp_path)
    # Still detected as a node project; RN patterns omitted because deps couldn't parse.
    assert "node" in labels
    assert "node_modules/" in patterns
    assert "ios/Pods/" not in patterns
