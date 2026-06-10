"""Syntactic lint pass over tree-sitter ASTs.

Unlike the graph analyses, lint rules are *local* properties of a file's
syntax (a call's syntactic neighbourhood), not relational ones. The pass
re-parses files with the cached tree-sitter parsers and walks each AST
once, dispatching enabled checkers at every node.

Findings surface through ``codegraph lint`` (whole repo) and merge into
``codegraph review`` output (diff-touched files) tagged ``kind: lint``.
"""
from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

import pathspec
import tree_sitter
import yaml

from codegraph.parsers.base import load_parser, node_text
from codegraph.parsers.python import _is_test_file as _is_py_test_file
from codegraph.parsers.typescript import EXT_TO_LANG
from codegraph.parsers.typescript import _is_test_file as _is_ts_test_file

if TYPE_CHECKING:
    from codegraph.review.rules import Finding

_TS_LANGS = frozenset({"typescript", "tsx", "javascript"})

_LOOP_NODE_TYPES = frozenset(
    {
        # TS / JS
        "for_statement",
        "for_in_statement",
        "while_statement",
        "do_statement",
    }
)

_SEVERITY_SCORE = {"low": 10, "med": 25, "high": 50, "critical": 80}


@dataclass
class LintRule:
    id: str
    check: str  # key into the checker registry
    severity: str  # low | med | high | critical
    message: str
    enabled: bool = True
    options: dict[str, Any] = field(default_factory=dict)


@dataclass
class LintFinding:
    rule_id: str
    severity: str
    message: str
    file: str
    line: int
    snippet: str = ""


@dataclass
class _LintContext:
    src: bytes
    rel_path: str
    language: str
    is_test_file: bool
    rule: LintRule
    loop_depth: int = 0


_Checker = Callable[[tree_sitter.Node, _LintContext], LintFinding | None]


def _snippet(node: tree_sitter.Node, src: bytes, limit: int = 120) -> str:
    text = node_text(node, src).strip().splitlines()[0] if node.end_byte > node.start_byte else ""
    return text[:limit]


def _format_message(rule: LintRule, **fmt: Any) -> str:
    try:
        return rule.message.format(**fmt)
    except (KeyError, IndexError):
        return rule.message


# --- Checkers -------------------------------------------------------------


def _check_console_in_prod(
    node: tree_sitter.Node, ctx: _LintContext
) -> LintFinding | None:
    """``console.*`` call in a non-test TS/JS file."""
    if ctx.language not in _TS_LANGS or ctx.is_test_file:
        return None
    if node.type != "call_expression":
        return None
    fn = node.child_by_field_name("function")
    if fn is None or fn.type != "member_expression":
        return None
    obj = fn.child_by_field_name("object")
    if obj is None or obj.type != "identifier":
        return None
    if node_text(obj, ctx.src) != "console":
        return None
    prop = fn.child_by_field_name("property")
    method = node_text(prop, ctx.src) if prop is not None else ""
    allow = {str(m) for m in ctx.rule.options.get("allow") or []}
    if method in allow:
        return None
    return LintFinding(
        rule_id=ctx.rule.id,
        severity=ctx.rule.severity,
        message=_format_message(ctx.rule, method=method),
        file=ctx.rel_path,
        line=node.start_point[0] + 1,
        snippet=_snippet(node, ctx.src),
    )


_CHECK_REGISTRY: dict[str, _Checker] = {
    "console-in-prod": _check_console_in_prod,
}


DEFAULT_LINT_RULES: list[LintRule] = [
    LintRule(
        id="console-in-prod",
        check="console-in-prod",
        severity="low",
        message="console.{method} call in production code",
    ),
]


# --- Rule loading ----------------------------------------------------------


def _rule_from_dict(data: dict[str, Any]) -> LintRule:
    return LintRule(
        id=str(data.get("id") or ""),
        check=str(data.get("check") or data.get("id") or ""),
        severity=str(data.get("severity") or "med"),
        message=str(data.get("message") or ""),
        enabled=bool(data.get("enabled", True)),
        options=cast(dict[str, Any], data.get("options") or {}),
    )


def load_lint_rules(rules_path: Path | None = None) -> list[LintRule]:
    """Load lint rules from YAML.

    When ``rules_path`` is ``None``, search for ``.codegraph/lint.yml`` and
    ``.codegraph.lint.yml`` in the current working directory. Falls back to
    :data:`DEFAULT_LINT_RULES` when no file is found.
    """
    candidates: list[Path] = []
    if rules_path is not None:
        candidates.append(rules_path)
    else:
        cwd = Path.cwd()
        candidates.extend(
            [
                cwd / ".codegraph" / "lint.yml",
                cwd / ".codegraph.lint.yml",
            ]
        )
    for path in candidates:
        if not path.exists():
            continue
        data = cast(dict[str, Any], yaml.safe_load(path.read_text()) or {})
        raw_rules = data.get("rules") or []
        rules: list[LintRule] = []
        for entry in raw_rules:
            if not isinstance(entry, dict):
                continue
            rule = _rule_from_dict(cast(dict[str, Any], entry))
            if rule.id and rule.check in _CHECK_REGISTRY and rule.enabled:
                rules.append(rule)
        if rules:
            return rules
    return [r for r in DEFAULT_LINT_RULES if r.enabled]


# --- File walk + AST dispatch ----------------------------------------------


def _lang_for(path: Path) -> str | None:
    suffix = path.suffix.lower()
    if suffix == ".py":
        return "python"
    return EXT_TO_LANG.get(suffix)


def _is_test_path(rel_path: str, language: str) -> bool:
    if language == "python":
        return _is_py_test_file(rel_path)
    return _is_ts_test_file(rel_path)


def _lint_file(
    path: Path, rel_path: str, language: str, rules: list[LintRule]
) -> list[LintFinding]:
    try:
        src = path.read_bytes()
    except OSError:
        return []
    try:
        tree = load_parser(language).parse(src)
    except Exception:
        return []

    is_test = _is_test_path(rel_path, language)
    findings: list[LintFinding] = []
    contexts = [
        _LintContext(
            src=src,
            rel_path=rel_path,
            language=language,
            is_test_file=is_test,
            rule=rule,
        )
        for rule in rules
    ]

    # Single iterative DFS carrying loop depth.
    stack: list[tuple[tree_sitter.Node, int]] = [(tree.root_node, 0)]
    while stack:
        node, loop_depth = stack.pop()
        for ctx in contexts:
            ctx.loop_depth = loop_depth
            checker = _CHECK_REGISTRY[ctx.rule.check]
            finding = checker(node, ctx)
            if finding is not None:
                findings.append(finding)
        child_depth = (
            loop_depth + 1 if node.type in _LOOP_NODE_TYPES else loop_depth
        )
        for child in reversed(node.children):
            stack.append((child, child_depth))
    return findings


def run_lint(
    repo_root: Path,
    *,
    files: Sequence[str] | None = None,
    rules: list[LintRule] | None = None,
    ignore: list[str] | None = None,
) -> list[LintFinding]:
    """Run the lint pass over ``repo_root``.

    ``files`` restricts the pass to the given repo-relative paths (used by
    ``codegraph review`` to lint only diff-touched files). Without it, the
    whole repo is walked using the same ignore patterns as the builder plus
    the analysis exclusions (test fixtures, static assets, examples).
    """
    from codegraph.analysis._common import is_excluded_path
    from codegraph.graph.builder import _BUILTIN_IGNORES, _IGNORE_DIRS

    rules = rules if rules is not None else load_lint_rules()
    rules = [r for r in rules if r.enabled and r.check in _CHECK_REGISTRY]
    if not rules:
        return []

    targets: list[tuple[Path, str]] = []
    if files is not None:
        for rel in files:
            path = repo_root / rel
            if path.is_file():
                targets.append((path, Path(rel).as_posix()))
    else:
        patterns = _BUILTIN_IGNORES + (ignore or [])
        spec = pathspec.PathSpec.from_lines("gitwildmatch", patterns)
        for path in sorted(repo_root.rglob("*")):
            if not path.is_file():
                continue
            try:
                rel = path.relative_to(repo_root).as_posix()
            except ValueError:
                continue
            if spec.match_file(rel):
                continue
            parts = Path(rel).parts
            if any(part in _IGNORE_DIRS for part in parts[:-1]):
                continue
            if is_excluded_path(rel):
                continue
            targets.append((path, rel))

    findings: list[LintFinding] = []
    for path, rel in targets:
        language = _lang_for(path)
        if language is None:
            continue
        findings.extend(_lint_file(path, rel, language, rules))

    findings.sort(key=lambda f: (f.file, f.line, f.rule_id))
    return findings


def to_review_findings(items: list[LintFinding]) -> list[Finding]:
    """Convert lint findings into review ``Finding`` objects (kind=lint)."""
    from codegraph.review.rules import Finding

    return [
        Finding(
            rule_id=item.rule_id,
            severity=item.severity,
            message=item.message,
            qualname="",
            file=item.file,
            line=item.line,
            score=_SEVERITY_SCORE.get(item.severity, 10),
            reasons=[item.snippet] if item.snippet else [],
            kind="lint",
        )
        for item in items
    ]
