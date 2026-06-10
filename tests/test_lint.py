"""Tests for the syntactic lint pass (analysis/lint.py)."""
from __future__ import annotations

import shutil
import textwrap
from pathlib import Path

from codegraph.analysis.lint import (
    DEFAULT_LINT_RULES,
    LintRule,
    load_lint_rules,
    run_lint,
    to_review_findings,
)

FIXTURES = Path(__file__).parent / "fixtures"


def _sample_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    shutil.copytree(FIXTURES / "lint_sample", repo)
    return repo


def test_console_in_prod_flags_non_test_file(tmp_path: Path) -> None:
    repo = _sample_repo(tmp_path)
    findings = run_lint(repo)
    files = {f.file for f in findings}
    assert "src/server.ts" in files
    # console.log, console.error, console.warn → 3 findings
    server = [f for f in findings if f.file == "src/server.ts"]
    assert len(server) == 3
    assert all(f.rule_id == "console-in-prod" for f in server)
    assert all(f.severity == "low" for f in server)
    assert server[0].line == 2


def test_console_in_test_file_not_flagged(tmp_path: Path) -> None:
    repo = _sample_repo(tmp_path)
    findings = run_lint(repo)
    assert not any(f.file == "src/app.test.ts" for f in findings)


def test_allow_option_whitelists_methods(tmp_path: Path) -> None:
    repo = _sample_repo(tmp_path)
    rules = [
        LintRule(
            id="console-in-prod",
            check="console-in-prod",
            severity="low",
            message="console.{method} in prod",
            options={"allow": ["warn", "error"]},
        )
    ]
    findings = run_lint(repo, rules=rules)
    methods = [f.snippet for f in findings]
    assert len(findings) == 1
    assert "console.log" in methods[0]


def test_files_arg_restricts_scope(tmp_path: Path) -> None:
    repo = _sample_repo(tmp_path)
    findings = run_lint(repo, files=["src/app.test.ts"])
    assert findings == []
    findings = run_lint(repo, files=["src/server.ts"])
    assert len(findings) == 3


def test_message_formats_method_name(tmp_path: Path) -> None:
    repo = _sample_repo(tmp_path)
    findings = run_lint(repo)
    messages = {f.message for f in findings}
    assert "console.log call in production code" in messages
    assert "console.warn call in production code" in messages


def test_load_lint_rules_defaults(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.chdir(tmp_path)
    rules = load_lint_rules()
    assert [r.id for r in rules] == [r.id for r in DEFAULT_LINT_RULES]


def test_load_lint_rules_from_yaml(tmp_path: Path) -> None:
    rules_file = tmp_path / "lint.yml"
    rules_file.write_text(
        textwrap.dedent(
            """\
            rules:
              - id: my-console
                check: console-in-prod
                severity: high
                message: "no console"
                options:
                  allow: [warn]
              - id: bogus-check
                check: does-not-exist
                severity: low
                message: "ignored"
            """
        )
    )
    rules = load_lint_rules(rules_file)
    assert len(rules) == 1
    assert rules[0].id == "my-console"
    assert rules[0].severity == "high"
    assert rules[0].options == {"allow": ["warn"]}


def test_to_review_findings_kind_lint(tmp_path: Path) -> None:
    repo = _sample_repo(tmp_path)
    findings = to_review_findings(run_lint(repo))
    assert findings
    assert all(f.kind == "lint" for f in findings)
    assert all(f.qualname == "" for f in findings)
    assert all(f.reasons for f in findings)  # snippet propagated


def test_ignores_unsupported_and_missing_files(tmp_path: Path) -> None:
    repo = _sample_repo(tmp_path)
    (repo / "notes.md").write_text("console.log in prose\n")
    findings = run_lint(repo, files=["notes.md", "missing.ts"])
    assert findings == []


def test_unfiltered_query_flags_missing_where(tmp_path: Path) -> None:
    repo = _sample_repo(tmp_path)
    findings = [
        f for f in run_lint(repo) if f.rule_id == "unfiltered-query"
    ]
    assert len(findings) == 1
    assert findings[0].file == "src/queries.ts"
    assert findings[0].line == 4
    assert "db.select.from" in findings[0].message


def test_unfiltered_query_filtered_chains_pass(tmp_path: Path) -> None:
    repo = _sample_repo(tmp_path)
    findings = [
        f for f in run_lint(repo) if f.rule_id == "unfiltered-query"
    ]
    lines = {f.line for f in findings if f.file == "src/queries.ts"}
    # .where (line 9) and .limit (line 14) chains are not flagged
    assert lines == {4}


def test_sensitive_literal_typescript(tmp_path: Path) -> None:
    repo = _sample_repo(tmp_path)
    findings = [
        f
        for f in run_lint(repo)
        if f.rule_id == "sensitive-literal" and f.file == "src/constants.ts"
    ]
    names = {f.snippet for f in findings}
    assert names == {
        "GENDER_OPTIONS",
        "apiKey",
        "SESSION_SECRET",
        "highEntropyBlob",
    }
    # tokenizerName, MAX_RETRIES, EMPTY_PASSWORD, envKey are NOT flagged
    assert "tokenizerName" not in names
    assert "EMPTY_PASSWORD" not in names


def test_sensitive_literal_python(tmp_path: Path) -> None:
    repo = _sample_repo(tmp_path)
    findings = [
        f
        for f in run_lint(repo)
        if f.rule_id == "sensitive-literal" and f.file == "src/settings.py"
    ]
    names = {f.snippet for f in findings}
    assert names == {"DATABASE_PASSWORD", "ETHNICITY_CHOICES"}


def test_sensitive_literal_redacts_value(tmp_path: Path) -> None:
    repo = _sample_repo(tmp_path)
    findings = [
        f for f in run_lint(repo) if f.rule_id == "sensitive-literal"
    ]
    for f in findings:
        assert "hunter2" not in f.snippet
        assert "hunter2" not in f.message
        assert "sk-test" not in f.snippet
        assert "sk-test" not in f.message
