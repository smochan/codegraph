"""Rule loading + evaluation against a ``GraphDiff``."""
from __future__ import annotations

import fnmatch
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

import networkx as nx
import yaml

from codegraph.review.differ import GraphDiff, NodeChange
from codegraph.review.risk import (
    _count_callers,
    _find_node_id,
    _has_callers_in_new,
    _hotspot_files,
    _introduces_cycle,
    _is_public_api,
    _param_count_changed,
    score_change,
)


@dataclass
class RuleMatch:
    qualname_prefix: str = ""
    qualname_regex: str = ""
    kind: str = ""
    file_glob: str = ""


@dataclass
class Rule:
    id: str
    when: str  # added_node|removed_node|modified_node|removed_referenced|
    # introduces_cycle|high_fan_in|new_dead_code
    severity: str  # low | med | high | critical
    message: str
    match: RuleMatch = field(default_factory=RuleMatch)
    threshold: int = 0


@dataclass
class Finding:
    rule_id: str
    severity: str
    message: str
    qualname: str
    file: str
    line: int
    score: int
    reasons: list[str] = field(default_factory=list)


DEFAULT_RULES: list[Rule] = [
    Rule(
        id="high-blast-radius",
        when="high_fan_in",
        severity="high",
        message="Modifying a symbol with {fan_in} callers",
        threshold=10,
    ),
    Rule(
        id="removed-referenced",
        when="removed_referenced",
        severity="critical",
        message="Removed symbol still referenced by callers",
    ),
    Rule(
        id="new-dead-code",
        when="new_dead_code",
        severity="low",
        message="Potentially unreachable new code",
    ),
    Rule(
        id="no-cycles",
        when="introduces_cycle",
        severity="high",
        message="PR introduces an import/call cycle",
    ),
    Rule(
        id="modified-signature",
        when="modified_node",
        severity="med",
        message="Modified node signature change",
    ),
]


_VALID_WHEN = {
    "added_node",
    "removed_node",
    "modified_node",
    "removed_referenced",
    "introduces_cycle",
    "high_fan_in",
    "new_dead_code",
}


_SEVERITY_RANK = {"low": 0, "med": 1, "high": 2, "critical": 3}


def severity_at_least(value: str, threshold: str) -> bool:
    return _SEVERITY_RANK.get(value, 0) >= _SEVERITY_RANK.get(threshold, 0)


def _rule_from_dict(data: dict[str, Any]) -> Rule:
    match_data = cast(dict[str, Any], data.get("match") or {})
    return Rule(
        id=str(data.get("id") or ""),
        when=str(data.get("when") or ""),
        severity=str(data.get("severity") or "med"),
        message=str(data.get("message") or ""),
        threshold=int(data.get("threshold") or 0),
        match=RuleMatch(
            qualname_prefix=str(match_data.get("qualname_prefix") or ""),
            qualname_regex=str(match_data.get("qualname_regex") or ""),
            kind=str(match_data.get("kind") or ""),
            file_glob=str(match_data.get("file_glob") or ""),
        ),
    )


def load_rules(rules_path: Path | None = None) -> list[Rule]:
    """Load rules from a YAML file.

    When ``rules_path`` is ``None``, search for ``.codegraph/rules.yml`` and
    ``.codegraph.rules.yml`` in the current working directory. Falls back to
    :data:`DEFAULT_RULES` when no file is found.
    """
    candidates: list[Path] = []
    if rules_path is not None:
        candidates.append(rules_path)
    else:
        cwd = Path.cwd()
        candidates.extend(
            [
                cwd / ".codegraph" / "rules.yml",
                cwd / ".codegraph.rules.yml",
            ]
        )
    for path in candidates:
        if not path.exists():
            continue
        text = path.read_text()
        data = cast(dict[str, Any], yaml.safe_load(text) or {})
        raw_rules = data.get("rules") or []
        rules: list[Rule] = []
        for entry in raw_rules:
            if not isinstance(entry, dict):
                continue
            rule = _rule_from_dict(cast(dict[str, Any], entry))
            if rule.id and rule.when in _VALID_WHEN:
                rules.append(rule)
        if rules:
            return rules
    return list(DEFAULT_RULES)


def _node_matches(rule: Rule, change: NodeChange) -> bool:
    m = rule.match
    if m.kind and m.kind != change.kind:
        return False
    if m.qualname_prefix and not change.qualname.startswith(m.qualname_prefix):
        return False
    if m.qualname_regex and not re.search(m.qualname_regex, change.qualname):
        return False
    return not (m.file_glob and not fnmatch.fnmatch(change.file, m.file_glob))


def _make_finding(
    rule: Rule,
    change: NodeChange,
    *,
    new_graph: nx.MultiDiGraph,
    old_graph: nx.MultiDiGraph,
    extra: dict[str, Any],
    fmt_kwargs: dict[str, Any] | None = None,
) -> Finding:
    risk = score_change(change, new_graph=new_graph, old_graph=old_graph, extra=extra)
    severity = rule.severity
    if severity_at_least(risk.level, severity):
        severity = risk.level
    fmt = dict(fmt_kwargs or {})
    fmt.setdefault("qualname", change.qualname)
    try:
        message = rule.message.format(**fmt)
    except (KeyError, IndexError):
        message = rule.message
    return Finding(
        rule_id=rule.id,
        severity=severity,
        message=message,
        qualname=change.qualname,
        file=change.file,
        line=change.line_start,
        score=risk.score,
        reasons=list(risk.reasons),
    )


def evaluate_rules(
    diff: GraphDiff,
    *,
    new_graph: nx.MultiDiGraph,
    old_graph: nx.MultiDiGraph,
    rules: list[Rule] | None = None,
) -> list[Finding]:
    """Evaluate ``rules`` against ``diff`` and return findings."""
    rules = rules if rules is not None else list(DEFAULT_RULES)

    hotspot_cache: dict[str, frozenset[str]] = {
        "files": _hotspot_files(new_graph)
    }
    cycle_cache: dict[str, int] = {}
    extra: dict[str, Any] = {
        "hotspot_cache": hotspot_cache,
        "cycle_cache": cycle_cache,
    }

    findings: list[Finding] = []
    cycle_introduced = _introduces_cycle(new_graph, old_graph, cycle_cache)

    for rule in rules:
        when = rule.when
        if when == "added_node":
            for change in diff.added_nodes:
                if not _node_matches(rule, change):
                    continue
                findings.append(
                    _make_finding(
                        rule, change,
                        new_graph=new_graph, old_graph=old_graph, extra=extra,
                    )
                )
        elif when == "removed_node":
            for change in diff.removed_nodes:
                if not _node_matches(rule, change):
                    continue
                findings.append(
                    _make_finding(
                        rule, change,
                        new_graph=new_graph, old_graph=old_graph, extra=extra,
                    )
                )
        elif when == "modified_node":
            for change in diff.modified_nodes:
                if not _node_matches(rule, change):
                    continue
                sig = change.details.get("signature") or {}
                old_sig = str(sig.get("old") or "")
                new_sig = str(sig.get("new") or "")
                if old_sig and new_sig and not _param_count_changed(
                    old_sig, new_sig
                ):
                    continue
                findings.append(
                    _make_finding(
                        rule, change,
                        new_graph=new_graph, old_graph=old_graph, extra=extra,
                    )
                )
        elif when == "removed_referenced":
            for change in diff.removed_nodes:
                if not _node_matches(rule, change):
                    continue
                old_id = _find_node_id(change.qualname, change.kind, old_graph)
                if old_id is None:
                    continue
                if not _has_callers_in_new(old_id, old_graph, new_graph):
                    continue
                findings.append(
                    _make_finding(
                        rule, change,
                        new_graph=new_graph, old_graph=old_graph, extra=extra,
                    )
                )
        elif when == "high_fan_in":
            threshold = rule.threshold or 10
            for change in diff.modified_nodes:
                if not _node_matches(rule, change):
                    continue
                new_id = _find_node_id(change.qualname, change.kind, new_graph)
                if new_id is None:
                    continue
                fan_in = _count_callers(new_id, new_graph)
                if fan_in < threshold:
                    continue
                findings.append(
                    _make_finding(
                        rule, change,
                        new_graph=new_graph, old_graph=old_graph, extra=extra,
                        fmt_kwargs={"fan_in": fan_in},
                    )
                )
        elif when == "new_dead_code":
            for change in diff.added_nodes:
                if not _node_matches(rule, change):
                    continue
                if change.kind not in ("FUNCTION", "METHOD"):
                    continue
                new_id = _find_node_id(change.qualname, change.kind, new_graph)
                if new_id is None:
                    continue
                if _count_callers(new_id, new_graph) > 0:
                    continue
                if _is_public_api(change.qualname):
                    continue
                findings.append(
                    _make_finding(
                        rule, change,
                        new_graph=new_graph, old_graph=old_graph, extra=extra,
                    )
                )
        elif when == "introduces_cycle":
            if not cycle_introduced:
                continue
            findings.append(
                Finding(
                    rule_id=rule.id,
                    severity=rule.severity,
                    message=rule.message,
                    qualname="",
                    file="",
                    line=0,
                    score=30,
                    reasons=["introduces import/call cycle"],
                )
            )

    findings.sort(
        key=lambda f: (
            -_SEVERITY_RANK.get(f.severity, 0),
            -f.score,
            f.qualname,
            f.rule_id,
        )
    )
    return findings
