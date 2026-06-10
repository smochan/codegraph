"""Tests for the ``codegraph lint`` command and review lint integration."""
from __future__ import annotations

import json
import os
import shutil
from collections.abc import Iterator
from pathlib import Path

import pytest
from typer.testing import CliRunner

from codegraph.cli import app

runner = CliRunner()
FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def lint_repo(tmp_path: Path) -> Iterator[Path]:
    repo = tmp_path / "repo"
    shutil.copytree(FIXTURES / "lint_sample", repo)
    orig = os.getcwd()
    os.chdir(repo)
    try:
        yield repo
    finally:
        os.chdir(orig)


def test_lint_markdown_output(lint_repo: Path) -> None:
    result = runner.invoke(app, ["lint"])
    assert result.exit_code == 0
    assert "console-in-prod" in result.stdout
    assert "src/server.ts" in result.stdout


def test_lint_fail_on_gates_exit_code(lint_repo: Path) -> None:
    result = runner.invoke(app, ["lint", "--fail-on", "low"])
    assert result.exit_code == 1
    result = runner.invoke(app, ["lint", "--fail-on", "high"])
    assert result.exit_code == 0


def test_lint_json_output(lint_repo: Path) -> None:
    out = lint_repo / "lint.json"
    result = runner.invoke(
        app, ["lint", "--format", "json", "--output", str(out)]
    )
    assert result.exit_code == 0
    payload = json.loads(out.read_text())
    findings = payload["findings"]
    assert len(findings) == 3
    assert all(f["kind"] == "lint" for f in findings)
    assert all(f["rule_id"] == "console-in-prod" for f in findings)


def test_lint_sarif_output(lint_repo: Path) -> None:
    out = lint_repo / "lint.sarif"
    result = runner.invoke(
        app, ["lint", "--format", "sarif", "--output", str(out)]
    )
    assert result.exit_code == 0
    payload = json.loads(out.read_text())
    assert payload["version"] == "2.1.0"
    results = payload["runs"][0]["results"]
    assert len(results) == 3
    assert all(r["properties"]["kind"] == "lint" for r in results)


def test_lint_custom_rules_file(lint_repo: Path) -> None:
    rules = lint_repo / "custom-lint.yml"
    rules.write_text(
        "rules:\n"
        "  - id: console-strict\n"
        "    check: console-in-prod\n"
        "    severity: critical\n"
        "    message: 'no console ever'\n"
    )
    result = runner.invoke(
        app, ["lint", "--rules", str(rules), "--fail-on", "critical"]
    )
    assert result.exit_code == 1
    assert "console-strict" in result.stdout


@pytest.fixture
def review_repo_with_lint(tmp_path: Path) -> Iterator[Path]:
    """v1 → baseline → v2 adds a console.log file; review should lint it."""
    repo = tmp_path / "repo"
    repo.mkdir()
    shutil.copytree(FIXTURES / "python_sample", repo / "pkg")
    orig = os.getcwd()
    os.chdir(repo)
    try:
        r = runner.invoke(app, ["build"])
        assert r.exit_code == 0, r.stdout
        r = runner.invoke(app, ["baseline", "save"])
        assert r.exit_code == 0, r.stdout
        # v2: add a TS file with a console.log so it shows up in the diff.
        src = repo / "web"
        src.mkdir()
        (src / "logger.ts").write_text(
            'export function log(msg: string): void {\n'
            "  console.log(msg);\n"
            "}\n"
        )
        r = runner.invoke(app, ["build"])
        assert r.exit_code == 0, r.stdout
        yield repo
    finally:
        os.chdir(orig)


def test_review_includes_lint_findings(review_repo_with_lint: Path) -> None:
    out = review_repo_with_lint / "review.json"
    result = runner.invoke(
        app, ["review", "--format", "json", "--output", str(out)]
    )
    assert result.exit_code in (0, 1)
    payload = json.loads(out.read_text())
    lint_findings = [
        f for f in payload["findings"] if f["kind"] == "lint"
    ]
    assert lint_findings
    assert lint_findings[0]["rule_id"] == "console-in-prod"
    assert lint_findings[0]["file"] == "web/logger.ts"


def test_review_no_lint_flag(review_repo_with_lint: Path) -> None:
    out = review_repo_with_lint / "review.json"
    result = runner.invoke(
        app,
        ["review", "--no-lint", "--format", "json", "--output", str(out)],
    )
    assert result.exit_code in (0, 1)
    payload = json.loads(out.read_text())
    assert not any(f["kind"] == "lint" for f in payload["findings"])
