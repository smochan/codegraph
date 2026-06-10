"""Syntactic lint pass over tree-sitter ASTs.

Unlike the graph analyses, lint rules are *local* properties of a file's
syntax (a call's syntactic neighbourhood), not relational ones. The pass
re-parses files with the cached tree-sitter parsers and walks each AST
once, dispatching enabled checkers at every node.

Findings surface through ``codegraph lint`` (whole repo) and merge into
``codegraph review`` output (diff-touched files) tagged ``kind: lint``.
"""
from __future__ import annotations

import math
import re
from collections import Counter
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


def _member_chain(
    node: tree_sitter.Node, src: bytes
) -> tuple[str, list[str]] | None:
    """Flatten a call chain like ``db.select().from(x).where(y)``.

    Returns ``(base, methods)`` — e.g. ``("db", ["select", "from", "where"])``
    — or ``None`` when the chain doesn't bottom out at an identifier.
    """
    methods: list[str] = []
    cur: tree_sitter.Node | None = node
    while cur is not None:
        if cur.type == "call_expression":
            cur = cur.child_by_field_name("function")
        elif cur.type == "member_expression":
            prop = cur.child_by_field_name("property")
            if prop is not None:
                methods.append(node_text(prop, src))
            cur = cur.child_by_field_name("object")
        elif cur.type in ("identifier", "this"):
            return node_text(cur, src), list(reversed(methods))
        else:
            return None
    return None


def _is_chain_root(node: tree_sitter.Node) -> bool:
    """True iff ``node`` is the outermost call of its member chain."""
    parent = node.parent
    if parent is None or parent.type != "member_expression":
        return True
    grandparent = parent.parent
    return grandparent is None or grandparent.type != "call_expression"


_DEFAULT_QUERY_PATTERN = r"\b(db|database)\.(select|query)\b"


def _check_unfiltered_query(
    node: tree_sitter.Node, ctx: _LintContext
) -> LintFinding | None:
    """Query-builder chain with ``from`` but no ``where``/``limit``."""
    if ctx.language not in _TS_LANGS or ctx.is_test_file:
        return None
    if node.type != "call_expression" or not _is_chain_root(node):
        return None
    chain = _member_chain(node, ctx.src)
    if chain is None:
        return None
    base, methods = chain
    chain_text = ".".join([base, *methods])
    pattern = str(ctx.rule.options.get("pattern") or _DEFAULT_QUERY_PATTERN)
    if not re.search(pattern, chain_text):
        return None
    if "from" not in methods:
        return None
    filters = set(ctx.rule.options.get("filters") or ["where", "limit"])
    if filters.intersection(methods):
        return None
    return LintFinding(
        rule_id=ctx.rule.id,
        severity=ctx.rule.severity,
        message=_format_message(ctx.rule, chain=chain_text),
        file=ctx.rel_path,
        line=node.start_point[0] + 1,
        snippet=_snippet(node, ctx.src),
    )


# Singular-only on purpose: plural forms are overwhelmingly counts or
# collections of non-secrets in real code (``tokens_in`` = LLM token
# count, ``_FIX_TOKENS`` = match words), while actual secrets are
# assigned to singular names (``token``, ``auth_token``, ``api_key``).
# Demographic category names stay matchable via their ``_``-suffixed
# forms (``gender_options`` → ``(^|_)gender(_|$)``).
_DEFAULT_SENSITIVE_PATTERN = (
    r"(^|_)(gender|ethnicity|race|veteran|disability|password|passwd|"
    r"secret|api_key|apikey|token|credential)(_|$)"
)
_ENTROPY_THRESHOLD = 4.5
_ENTROPY_MIN_LEN = 20
_ENTROPY_MAX_LEN = 512
_WHITESPACE_RE = re.compile(r"\s")
_CAMEL_RE = re.compile(r"([a-z0-9])([A-Z])")

_TS_LITERAL_TYPES = frozenset(
    {"string", "template_string", "array", "object", "number"}
)
_PY_LITERAL_TYPES = frozenset(
    {"string", "list", "dictionary", "tuple", "integer", "float"}
)


def _identifier_words(name: str) -> str:
    """Normalize camelCase / SCREAMING_SNAKE to snake_case for matching."""
    return _CAMEL_RE.sub(r"\1_\2", name).lower()


def _shannon_entropy(text: str) -> float:
    if not text:
        return 0.0
    counts = Counter(text)
    total = len(text)
    return -sum(
        (n / total) * math.log2(n / total) for n in counts.values()
    )


def _string_body(node: tree_sitter.Node, src: bytes) -> str:
    text = node_text(node, src)
    return text.strip("\"'`")


def _assignment_parts(
    node: tree_sitter.Node, language: str
) -> tuple[tree_sitter.Node, tree_sitter.Node] | None:
    """Return (lhs, rhs) for an assignment-shaped node, else None."""
    if language == "python":
        if node.type != "assignment":
            return None
        left = node.child_by_field_name("left")
        right = node.child_by_field_name("right")
    elif node.type == "variable_declarator":
        left = node.child_by_field_name("name")
        right = node.child_by_field_name("value")
    elif node.type == "assignment_expression":
        left = node.child_by_field_name("left")
        right = node.child_by_field_name("right")
    elif node.type == "pair":
        left = node.child_by_field_name("key")
        right = node.child_by_field_name("value")
    else:
        return None
    if left is None or right is None:
        return None
    return left, right


def _check_sensitive_literal(
    node: tree_sitter.Node, ctx: _LintContext
) -> LintFinding | None:
    """Sensitive identifier assigned a literal, or a high-entropy string."""
    if ctx.is_test_file:
        return None
    parts = _assignment_parts(node, ctx.language)
    if parts is None:
        return None
    left, right = parts
    if left.type not in ("identifier", "property_identifier"):
        return None
    name = node_text(left, ctx.src)
    literal_types = (
        _PY_LITERAL_TYPES if ctx.language == "python" else _TS_LITERAL_TYPES
    )
    if right.type not in literal_types:
        return None

    pattern = str(
        ctx.rule.options.get("pattern") or _DEFAULT_SENSITIVE_PATTERN
    )
    name_matches = bool(re.search(pattern, _identifier_words(name)))

    high_entropy = False
    if not name_matches and right.type in ("string", "template_string"):
        body = _string_body(right, ctx.src)
        # Secret-shaped only: tokens have no whitespace and a bounded
        # length. Long prose / HTML templates also clear the entropy bar
        # but are not secrets.
        high_entropy = (
            _ENTROPY_MIN_LEN <= len(body) <= _ENTROPY_MAX_LEN
            and not _WHITESPACE_RE.search(body)
            and _shannon_entropy(body) > _ENTROPY_THRESHOLD
        )

    if not name_matches and not high_entropy:
        return None
    # Empty-string placeholders are not findings.
    if right.type in ("string", "template_string") and not _string_body(
        right, ctx.src
    ):
        return None

    reason = "sensitive identifier" if name_matches else "high-entropy string"
    return LintFinding(
        rule_id=ctx.rule.id,
        severity=ctx.rule.severity,
        message=_format_message(ctx.rule, name=name, reason=reason),
        file=ctx.rel_path,
        line=node.start_point[0] + 1,
        # Deliberately redact the RHS: never echo a potential secret
        # value into reports, CI logs, or PR comments.
        snippet=name,
    )


_CHECK_REGISTRY: dict[str, _Checker] = {
    "console-in-prod": _check_console_in_prod,
    "unfiltered-query": _check_unfiltered_query,
    "sensitive-literal": _check_sensitive_literal,
}


DEFAULT_LINT_RULES: list[LintRule] = [
    LintRule(
        id="console-in-prod",
        check="console-in-prod",
        severity="low",
        message="console.{method} call in production code",
    ),
    LintRule(
        id="unfiltered-query",
        check="unfiltered-query",
        severity="med",
        message="Query builder chain `{chain}` has no .where/.limit",
    ),
    LintRule(
        id="sensitive-literal",
        check="sensitive-literal",
        severity="med",
        message="Literal assigned to `{name}` looks sensitive ({reason})",
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
