"""Taint source / sink / sanitizer catalog.

Spec: docs/GAP_ANALYSIS_VS_LLM_REVIEWER.md §Capability A

Provides three dataclasses:

* :class:`SourceSpec`  — identifies where untrusted data originates.
* :class:`SinkSpec`    — identifies where tainted data is dangerous.
* :class:`SanitizerSpec` — identifies calls that clear taint for a sink class.

Instances are loaded from YAML (search order:
``.codegraph/taint.yml`` → ``.codegraph.taint.yml`` → bundled defaults).

The YAML format mirrors lint.yml:

.. code-block:: yaml

   sources:
     - id: my_source
       class_label: http_request
       match: "custom_param_func"
       where: call_result

   sinks:
     - id: my_sink
       class_label: network
       match: "my_http_call"
       severity: high

   sanitizers:
     - id: my_sanitizer
       match: "my_validator"
       clears: [network, sql]

The bundled defaults cover the most common Python web patterns.

**Design note on os.environ:**
``os.environ`` is intentionally NOT treated as an untrusted source.  Environment
variables are operator-controlled configuration, not user-supplied data.  Treating
them as taint sources would produce enormous false-positive rates in normal Python
applications.  If a project reads user-supplied data from the environment (unusual),
override the catalog by adding a custom source rule in ``.codegraph/taint.yml``.
"""
from __future__ import annotations

import contextlib
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

import yaml

# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

_VALID_SOURCE_CLASSES = frozenset({
    "http_request",
    "fetch_response",
    "llm_output",
    "file_read",
    "scraped_dom",
})

_VALID_SINK_CLASSES = frozenset({
    "network",
    "sql",
    "eval",
    "dom",
    "path",
    "exec",
})

_VALID_WHERE = frozenset({"call_result", "route_param"})

# Severity per sink class (used as default when not overridden).
SINK_CLASS_SEVERITY: dict[str, str] = {
    "network": "high",
    "sql": "critical",
    "eval": "critical",
    "dom": "high",
    "path": "med",
    "exec": "critical",
}


@dataclass
class SourceSpec:
    """Describes where untrusted data originates.

    Attributes:
        id:          Unique rule identifier.
        class_label: Semantic class of the source (e.g. ``http_request``).
        match:       Regex matched against the callee text.  For
                     ``route_param`` sources the regex is matched against the
                     enclosing handler's qualname (unused — all route-handler
                     params are seeded when ``where="route_param"``).
        where:       ``"call_result"`` — the return value of a matching call is
                     tainted; ``"route_param"`` — PARAMETER nodes whose
                     enclosing function has an incoming ROUTE edge are seeded.
    """

    id: str
    class_label: str
    match: str
    where: str = "call_result"
    _compiled: re.Pattern[str] | None = field(
        default=None, init=False, repr=False, compare=False
    )

    def __post_init__(self) -> None:
        if self.class_label not in _VALID_SOURCE_CLASSES:
            raise ValueError(
                f"SourceSpec {self.id!r}: unknown class_label {self.class_label!r}. "
                f"Valid: {sorted(_VALID_SOURCE_CLASSES)}"
            )
        if self.where not in _VALID_WHERE:
            raise ValueError(
                f"SourceSpec {self.id!r}: unknown where={self.where!r}. "
                f"Valid: {sorted(_VALID_WHERE)}"
            )
        self._compiled = re.compile(self.match)

    def matches(self, text: str) -> bool:
        """Return True if *text* (callee text / qualname) matches this source.

        Returns False for ``route_param`` sources (they are seeded structurally
        from ROUTE-edge handler parameters, not by matching callee text), and
        for sources with an empty match pattern.
        """
        if self.where == "route_param":
            # route_param sources are seeded structurally; never used for
            # callee-text matching.  An empty pattern would match everything,
            # producing false positives (e.g. matching os.environ).
            return False
        if not self.match:
            return False
        if self._compiled is None:
            self._compiled = re.compile(self.match)
        return bool(self._compiled.search(text))


@dataclass
class SinkSpec:
    """Describes where tainted data reaching this call is dangerous.

    Attributes:
        id:            Unique rule identifier.
        class_label:   Semantic class of the sink.
        match:         Regex matched against callee text.
        severity:      Override for the class-level default severity.
        arg_positions: When set, only these argument positions are dangerous.
                       Position 0 = first argument.  ``None`` means all args
                       are dangerous.
    """

    id: str
    class_label: str
    match: str
    severity: str = ""
    arg_positions: list[int] | None = None
    _compiled: re.Pattern[str] | None = field(
        default=None, init=False, repr=False, compare=False
    )

    def __post_init__(self) -> None:
        if self.class_label not in _VALID_SINK_CLASSES:
            raise ValueError(
                f"SinkSpec {self.id!r}: unknown class_label {self.class_label!r}. "
                f"Valid: {sorted(_VALID_SINK_CLASSES)}"
            )
        if not self.severity:
            self.severity = SINK_CLASS_SEVERITY.get(self.class_label, "high")
        self._compiled = re.compile(self.match)

    def matches(self, callee_text: str) -> bool:
        if self._compiled is None:
            self._compiled = re.compile(self.match)
        return bool(self._compiled.search(callee_text))

    def position_is_dangerous(self, position: int | None) -> bool:
        """Return True if the given argument position (or kwarg) is dangerous."""
        if self.arg_positions is None:
            return True
        if position is None:
            # Keyword argument — assume dangerous when no restriction.
            return True
        return position in self.arg_positions


@dataclass
class SanitizerSpec:
    """Describes a call that clears taint for specific sink classes.

    Attributes:
        id:     Unique rule identifier.
        match:  Regex matched against the callee text.
        clears: List of sink class_labels this sanitizer clears.
    """

    id: str
    match: str
    clears: list[str] = field(default_factory=list)
    _compiled: re.Pattern[str] | None = field(
        default=None, init=False, repr=False, compare=False
    )

    def __post_init__(self) -> None:
        self._compiled = re.compile(self.match)

    def matches(self, callee_text: str) -> bool:
        if self._compiled is None:
            self._compiled = re.compile(self.match)
        return bool(self._compiled.search(callee_text))


@dataclass
class TaintCatalog:
    """Aggregated collection of sources, sinks, and sanitizers."""

    sources: list[SourceSpec] = field(default_factory=list)
    sinks: list[SinkSpec] = field(default_factory=list)
    sanitizers: list[SanitizerSpec] = field(default_factory=list)

    def find_source(self, callee_text: str) -> SourceSpec | None:
        """Return first SourceSpec matching *callee_text*, or None."""
        for spec in self.sources:
            if spec.matches(callee_text):
                return spec
        return None

    def find_sink(self, callee_text: str) -> SinkSpec | None:
        """Return first SinkSpec matching *callee_text*, or None."""
        for spec in self.sinks:
            if spec.matches(callee_text):
                return spec
        return None

    def find_sanitizers(self, callee_text: str) -> list[SanitizerSpec]:
        """Return all SanitizerSpecs matching *callee_text*."""
        return [s for s in self.sanitizers if s.matches(callee_text)]

    def route_param_sources(self) -> list[SourceSpec]:
        """Return all sources with where=="route_param"."""
        return [s for s in self.sources if s.where == "route_param"]

    def call_result_sources(self) -> list[SourceSpec]:
        """Return all sources with where=="call_result"."""
        return [s for s in self.sources if s.where == "call_result"]


# ---------------------------------------------------------------------------
# Bundled default catalog
# ---------------------------------------------------------------------------

# HTTP request input — these are call_result sources (the function returns
# user-controlled data).
_DEFAULT_SOURCES: list[dict[str, Any]] = [
    # Flask / FastAPI / Django: request object attribute access patterns.
    # request.args.get(), request.form.get(), request.get_json(), etc.
    {
        "id": "flask_request",
        "class_label": "http_request",
        # Match common Flask/FastAPI request attribute chains.
        "match": r"\brequest\.(args|form|json|get_json|body|params|query|data|files|values)",
        "where": "call_result",
    },
    # Direct call to request.get_json() / request.json() / request.body
    {
        "id": "flask_request_method",
        "class_label": "http_request",
        "match": r"\brequest\.(get_json|json|body|get_data)\b",
        "where": "call_result",
    },
    # Python builtins: input() always reads from stdin (user).
    {
        "id": "builtin_input",
        "class_label": "http_request",
        "match": r"^input$",
        "where": "call_result",
    },
    # requests / httpx / aiohttp response bodies — treated as fetch_response.
    # The response object's .text, .json(), .content, .read() all carry
    # potentially attacker-controlled data (e.g., SSRF-fetched content).
    {
        "id": "http_response_text",
        "class_label": "fetch_response",
        "match": r"\.(text|json|content|read|iter_content|iter_lines)\b",
        "where": "call_result",
    },
    # LLM API response text — output from language models is untrusted.
    {
        "id": "llm_completion",
        "class_label": "llm_output",
        "match": (
            r"(openai|anthropic|claude|gpt|llm|chat|completion)"
            r".*\.(create|complete|generate|chat|invoke|run)\b"
        ),
        "where": "call_result",
    },
    # File reads — content from the filesystem may be attacker-controlled.
    {
        "id": "file_read",
        "class_label": "file_read",
        "match": r"\.(read|readlines|readline)\b|open\(",
        "where": "call_result",
    },
    # Scraped DOM / web scraping — playwright, selenium, BeautifulSoup.
    {
        "id": "scraped_dom",
        "class_label": "scraped_dom",
        "match": (
            r"(page\.(inner_text|text_content|inner_html|evaluate|query_selector|url)"
            r"|soup\.(get_text|find|select|text)"
            r"|\bscraped\b)"
        ),
        "where": "call_result",
    },
    # Route handler parameters — seeded from ROUTE-decorated functions.
    # The 'match' field is unused for route_param sources; all PARAMETER
    # nodes of route handlers are seeded unconditionally.
    {
        "id": "route_params",
        "class_label": "http_request",
        "match": r"",  # unused for route_param
        "where": "route_param",
    },
]

_DEFAULT_SINKS: list[dict[str, Any]] = [
    # --- Network sinks (SSRF) ---
    {
        "id": "requests_get",
        "class_label": "network",
        "match": r"\brequests\.(get|post|put|delete|patch|head|request|Session|session)\b",
        "severity": "high",
        "arg_positions": [0],
    },
    {
        "id": "httpx_request",
        "class_label": "network",
        "match": r"\bhttpx\.(get|post|put|delete|patch|head|request|Client|AsyncClient)\b",
        "severity": "high",
        "arg_positions": [0],
    },
    {
        "id": "aiohttp_request",
        "class_label": "network",
        "match": r"\baiohttp\.(request|ClientSession)\b|session\.(get|post|put|delete|patch)\b",
        "severity": "high",
        "arg_positions": [0],
    },
    {
        "id": "fetch_axios",
        "class_label": "network",
        "match": r"\b(fetch|axios|axios\.(get|post|put|delete|patch|request))\b",
        "severity": "high",
        "arg_positions": [0],
    },
    {
        "id": "playwright_goto",
        "class_label": "network",
        "match": r"page\.(goto|navigate|set_content)\b",
        "severity": "high",
        "arg_positions": [0],
    },
    # --- SQL injection sinks ---
    {
        "id": "cursor_execute",
        "class_label": "sql",
        "match": r"\b(cursor|db|session|conn|connection)\.(execute|executemany|executescript|query|raw)\b",
        "severity": "critical",
        "arg_positions": [0],
    },
    {
        "id": "sqlalchemy_execute",
        "class_label": "sql",
        "match": r"session\.execute\b|db\.execute\b",
        "severity": "critical",
        "arg_positions": [0],
    },
    # --- eval / code execution ---
    {
        "id": "builtin_eval",
        "class_label": "eval",
        "match": r"^eval$",
        "severity": "critical",
        "arg_positions": [0],
    },
    {
        "id": "builtin_exec",
        "class_label": "eval",
        "match": r"^exec$",
        "severity": "critical",
        "arg_positions": [0],
    },
    # --- OS command execution ---
    {
        "id": "subprocess_run",
        "class_label": "exec",
        "match": r"\bsubprocess\.(run|call|check_call|check_output|Popen)\b",
        "severity": "critical",
        "arg_positions": [0],
    },
    {
        "id": "os_system",
        "class_label": "exec",
        "match": r"\bos\.(system|popen|execvp|execv|execve|spawnl|spawnle|spawnv)\b",
        "severity": "critical",
        "arg_positions": [0],
    },
    {
        "id": "shlex_split_sink",
        "class_label": "exec",
        # shlex.split itself is a sanitizer, but shell=True with a tainted
        # string is dangerous. Pattern matches the dangerous shell= arg form.
        "match": r"\b(run|call|Popen)\b",
        "severity": "critical",
        "arg_positions": [0],
    },
    # --- Path traversal ---
    {
        "id": "open_call",
        "class_label": "path",
        "match": r"^open$",
        "severity": "med",
        "arg_positions": [0],
    },
    {
        "id": "path_operations",
        "class_label": "path",
        "match": r"\bPath\b|os\.path\.(join|abspath|realpath|exists)\b",
        "severity": "med",
        "arg_positions": [0],
    },
    # --- DOM-based XSS ---
    {
        "id": "dangerous_html",
        "class_label": "dom",
        "match": r"dangerouslySetInnerHTML|innerHTML\s*=|document\.write\b",
        "severity": "high",
        "arg_positions": None,
    },
]

_DEFAULT_SANITIZERS: list[dict[str, Any]] = [
    # URL allowlist / safe-URL validators — clears network sink taint.
    {
        "id": "safe_url_check",
        "match": r"is_safe_public_url|is_safe_url|validate_url|check_url|allowlist_url",
        "clears": ["network"],
    },
    # HTML escaping — clears DOM sink taint.
    {
        "id": "html_escape",
        "match": r"\bescape\b|bleach\.clean\b|html\.escape\b|markupsafe\.escape\b",
        "clears": ["dom"],
    },
    # Shell quoting — clears exec sink taint.
    {
        "id": "shell_quote",
        "match": r"shlex\.quote\b|pipes\.quote\b",
        "clears": ["exec"],
    },
    # Zod / schema validation — clears all sink classes (strong validation).
    {
        "id": "zod_parse",
        "match": r"\.parse\b|\.safeParse\b|\.parseAsync\b",
        "clears": ["network", "sql", "eval", "dom", "path", "exec"],
    },
    # Pydantic / marshmallow validation.
    {
        "id": "pydantic_validate",
        "match": r"\.model_validate\b|\.parse_obj\b|Schema\(",
        "clears": ["network", "sql", "eval", "dom", "path", "exec"],
    },
    # Parameterized SQL — parameterized queries clear SQL sink taint.
    # Pattern: calling execute with tuple/list second arg is safe, but we
    # can't detect that statically. Instead we check for known safe wrappers.
    {
        "id": "sql_escape",
        "match": r"sql_escape\b|quote_identifier\b|literal_column\b",
        "clears": ["sql"],
    },
]


def _build_default_catalog() -> TaintCatalog:
    catalog = TaintCatalog()
    for raw in _DEFAULT_SOURCES:
        with contextlib.suppress(KeyError, ValueError):
            catalog.sources.append(
                SourceSpec(
                    id=str(raw["id"]),
                    class_label=str(raw["class_label"]),
                    match=str(raw["match"]),
                    where=str(raw.get("where", "call_result")),
                )
            )
    for raw in _DEFAULT_SINKS:
        ap = raw.get("arg_positions")
        with contextlib.suppress(KeyError, ValueError):
            catalog.sinks.append(
                SinkSpec(
                    id=str(raw["id"]),
                    class_label=str(raw["class_label"]),
                    match=str(raw["match"]),
                    severity=str(raw.get("severity", "")),
                    arg_positions=([int(x) for x in ap] if ap is not None else None),
                )
            )
    for raw in _DEFAULT_SANITIZERS:
        with contextlib.suppress(KeyError, ValueError):
            catalog.sanitizers.append(
                SanitizerSpec(
                    id=str(raw["id"]),
                    match=str(raw["match"]),
                    clears=list(raw.get("clears") or []),
                )
            )
    return catalog


_DEFAULT_CATALOG: TaintCatalog | None = None


def _get_default_catalog() -> TaintCatalog:
    global _DEFAULT_CATALOG
    if _DEFAULT_CATALOG is None:
        _DEFAULT_CATALOG = _build_default_catalog()
    return _DEFAULT_CATALOG


# ---------------------------------------------------------------------------
# YAML loader
# ---------------------------------------------------------------------------


def _source_from_dict(data: dict[str, Any]) -> SourceSpec | None:
    try:
        return SourceSpec(
            id=str(data.get("id") or ""),
            class_label=str(data.get("class_label") or ""),
            match=str(data.get("match") or ""),
            where=str(data.get("where") or "call_result"),
        )
    except (KeyError, ValueError):
        return None


def _sink_from_dict(data: dict[str, Any]) -> SinkSpec | None:
    try:
        ap = data.get("arg_positions")
        return SinkSpec(
            id=str(data.get("id") or ""),
            class_label=str(data.get("class_label") or ""),
            match=str(data.get("match") or ""),
            severity=str(data.get("severity") or ""),
            arg_positions=([int(x) for x in ap] if ap is not None else None),
        )
    except (KeyError, ValueError):
        return None


def _sanitizer_from_dict(data: dict[str, Any]) -> SanitizerSpec | None:
    try:
        return SanitizerSpec(
            id=str(data.get("id") or ""),
            match=str(data.get("match") or ""),
            clears=list(data.get("clears") or []),
        )
    except (KeyError, ValueError):
        return None


def load_taint_catalog(
    rules_path: Path | None = None,
    *,
    search_cwd: Path | None = None,
) -> TaintCatalog:
    """Load the taint catalog from YAML, falling back to bundled defaults.

    Search order:
    1. ``rules_path`` (explicit override)
    2. ``<search_cwd>/.codegraph/taint.yml``
    3. ``<search_cwd>/.codegraph.taint.yml``
    4. Built-in defaults

    When a YAML file is found, it is merged with the defaults: the file's
    entries are appended AFTER the defaults so that custom rules extend
    rather than replace the catalog.  Set a ``replace: true`` top-level key
    in the YAML to suppress the defaults entirely.
    """
    candidates: list[Path] = []
    if rules_path is not None:
        candidates.append(rules_path)
    else:
        cwd = search_cwd or Path.cwd()
        candidates.extend([
            cwd / ".codegraph" / "taint.yml",
            cwd / ".codegraph.taint.yml",
        ])

    for path in candidates:
        if not path.exists():
            continue
        raw_data = cast(
            dict[str, Any], yaml.safe_load(path.read_text()) or {}
        )
        replace = bool(raw_data.get("replace", False))

        catalog: TaintCatalog
        # Start from a fresh default catalog, or empty when replacing entirely.
        catalog = TaintCatalog() if replace else _build_default_catalog()

        for entry in raw_data.get("sources") or []:
            if not isinstance(entry, dict):
                continue
            spec = _source_from_dict(cast(dict[str, Any], entry))
            if spec is not None and spec.id:
                catalog.sources.append(spec)

        for entry in raw_data.get("sinks") or []:
            if not isinstance(entry, dict):
                continue
            spec2 = _sink_from_dict(cast(dict[str, Any], entry))
            if spec2 is not None and spec2.id:
                catalog.sinks.append(spec2)

        for entry in raw_data.get("sanitizers") or []:
            if not isinstance(entry, dict):
                continue
            spec3 = _sanitizer_from_dict(cast(dict[str, Any], entry))
            if spec3 is not None and spec3.id:
                catalog.sanitizers.append(spec3)

        return catalog

    return _get_default_catalog()


__all__ = [
    "SINK_CLASS_SEVERITY",
    "SanitizerSpec",
    "SinkSpec",
    "SourceSpec",
    "TaintCatalog",
    "load_taint_catalog",
]
