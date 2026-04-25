"""Tests for the Phase 4 CLI commands (review, baseline, hook)."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from collections.abc import Iterator
from pathlib import Path

import pytest
from typer.testing import CliRunner

from codegraph.cli import app

runner = CliRunner()
FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def repo_with_baseline(tmp_path: Path) -> Iterator[Path]:
    repo = tmp_path / "repo"
    repo.mkdir()
    shutil.copytree(FIXTURES / "python_sample", repo / "pkg")
    orig = os.getcwd()
    os.chdir(repo)
    try:
        # Build initial graph and snapshot baseline.
        r = runner.invoke(app, ["build"])
        assert r.exit_code == 0, r.stdout
        r = runner.invoke(app, ["baseline", "save"])
        assert r.exit_code == 0, r.stdout
        # Mutate the repo to v2.
        shutil.rmtree(repo / "pkg")
        shutil.copytree(FIXTURES / "python_sample_v2", repo / "pkg")
        r = runner.invoke(app, ["build"])
        assert r.exit_code == 0, r.stdout
        yield repo
    finally:
        os.chdir(orig)


def test_baseline_status_present(repo_with_baseline: Path) -> None:
    result = runner.invoke(app, ["baseline", "status"])
    assert result.exit_code == 0
    assert "baseline present" in result.stdout


def test_baseline_status_missing(tmp_path: Path) -> None:
    orig = os.getcwd()
    os.chdir(tmp_path)
    try:
        result = runner.invoke(app, ["baseline", "status"])
    finally:
        os.chdir(orig)
    assert result.exit_code == 1


def test_review_no_baseline_returns_2(tmp_path: Path) -> None:
    repo = tmp_path / "r"
    repo.mkdir()
    shutil.copytree(FIXTURES / "python_sample", repo / "pkg")
    orig = os.getcwd()
    os.chdir(repo)
    try:
        r = runner.invoke(app, ["build"])
        assert r.exit_code == 0
        result = runner.invoke(app, ["review"])
    finally:
        os.chdir(orig)
    assert result.exit_code == 2


def test_review_markdown(repo_with_baseline: Path) -> None:
    result = runner.invoke(app, ["review", "--format", "markdown"])
    # Exit code may be 0 or 1 depending on findings severity.
    assert result.exit_code in (0, 1)
    assert "codegraph review" in result.stdout
    assert "Findings" in result.stdout


def test_review_json(repo_with_baseline: Path) -> None:
    out = repo_with_baseline / "review.json"
    result = runner.invoke(
        app, ["review", "--format", "json", "--output", str(out)]
    )
    assert result.exit_code in (0, 1)
    payload = json.loads(out.read_text())
    assert "diff" in payload
    assert "findings" in payload


def test_review_sarif(repo_with_baseline: Path) -> None:
    out = repo_with_baseline / "review.sarif"
    result = runner.invoke(
        app, ["review", "--format", "sarif", "--output", str(out)]
    )
    assert result.exit_code in (0, 1)
    payload = json.loads(out.read_text())
    assert payload["version"] == "2.1.0"
    assert payload["runs"]


def test_hook_install_and_uninstall(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    orig = os.getcwd()
    os.chdir(repo)
    try:
        r = runner.invoke(app, ["hook", "install"])
        assert r.exit_code == 0
        hook_path = repo / ".git" / "hooks" / "pre-push"
        assert hook_path.exists()
        assert "codegraph-managed-hook" in hook_path.read_text()
        # idempotent re-install
        r = runner.invoke(app, ["hook", "install"])
        assert r.exit_code == 0
        r = runner.invoke(app, ["hook", "uninstall"])
        assert r.exit_code == 0
        assert not hook_path.exists()
    finally:
        os.chdir(orig)


def test_hook_install_refuses_foreign_hook(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    hooks_dir = repo / ".git" / "hooks"
    hooks_dir.mkdir(parents=True, exist_ok=True)
    (hooks_dir / "pre-push").write_text("#!/bin/sh\necho hi\n")
    orig = os.getcwd()
    os.chdir(repo)
    try:
        r = runner.invoke(app, ["hook", "install"])
    finally:
        os.chdir(orig)
    assert r.exit_code == 1
