"""Tolerant tsconfig.json / jsconfig.json path-alias loader.

Reads ``compilerOptions.paths`` and ``compilerOptions.baseUrl`` from the
nearest ``tsconfig.json`` or ``jsconfig.json`` found at *repo_root*.

The parser is intentionally lenient:
- strips ``//`` and ``/* ... */`` comments before handing the text to
  ``json.loads`` (tsconfig allows both; the JSON spec does not);
- strips trailing commas before closing ``]`` or ``}`` tokens.

No new dependency is introduced — only stdlib.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

# ---------------------------------------------------------------------------
# Tolerant JSON parser helpers
# ---------------------------------------------------------------------------

# Remove // line comments (not inside strings — good enough for tsconfig).
_LINE_COMMENT_RE = re.compile(r'(?m)//[^\n]*')
# Remove /* ... */ block comments.
_BLOCK_COMMENT_RE = re.compile(r'/\*.*?\*/', re.DOTALL)
# Remove trailing commas before ] or }.
_TRAILING_COMMA_RE = re.compile(r',\s*(?=[}\]])')


def _tolerant_loads(text: str) -> object:
    """Parse JSON with comments and trailing commas stripped."""
    text = _BLOCK_COMMENT_RE.sub('', text)
    text = _LINE_COMMENT_RE.sub('', text)
    text = _TRAILING_COMMA_RE.sub('', text)
    return json.loads(text)


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

@dataclass
class TsPathMapping:
    """Resolved path mapping table from tsconfig/jsconfig."""

    # base_url is the absolute path of compilerOptions.baseUrl (if set).
    base_url: Path | None = None

    # paths maps a pattern key (e.g. "@/*") to a list of replacement patterns
    # (e.g. ["./src/*"]).  The raw strings from compilerOptions.paths.
    paths: dict[str, list[str]] = field(default_factory=dict)

    def is_empty(self) -> bool:
        return not self.paths and self.base_url is None


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------

_CONFIG_NAMES = ("tsconfig.json", "jsconfig.json")


def load_ts_path_mapping(repo_root: Path) -> TsPathMapping:
    """Return the TsPathMapping for *repo_root*, or an empty one if absent.

    Searches for ``tsconfig.json`` then ``jsconfig.json`` directly inside
    *repo_root* (not recursively).  Silently returns empty on any parse
    error so as not to break the build pass on malformed configs.
    """
    for name in _CONFIG_NAMES:
        config_path = repo_root / name
        if not config_path.is_file():
            continue
        try:
            data = _tolerant_loads(config_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(data, dict):
            continue
        compiler_opts = data.get("compilerOptions")
        if not isinstance(compiler_opts, dict):
            return TsPathMapping()

        base_url: Path | None = None
        raw_base = compiler_opts.get("baseUrl")
        if isinstance(raw_base, str) and raw_base:
            candidate = (repo_root / raw_base).resolve()
            if candidate.is_dir():
                base_url = candidate

        raw_paths = compiler_opts.get("paths")
        paths: dict[str, list[str]] = {}
        if isinstance(raw_paths, dict):
            for key, val in raw_paths.items():
                if not isinstance(key, str):
                    continue
                if isinstance(val, list):
                    cleaned = [v for v in val if isinstance(v, str)]
                    if cleaned:
                        paths[key] = cleaned

        return TsPathMapping(base_url=base_url, paths=paths)
    return TsPathMapping()


# ---------------------------------------------------------------------------
# Alias rewriting
# ---------------------------------------------------------------------------

def rewrite_alias(
    import_target: str,
    mapping: TsPathMapping,
    repo_root: Path,
) -> str | None:
    """Rewrite *import_target* using the tsconfig path mapping.

    Returns the rewritten dotted-qualname string if a mapping matches, or
    ``None`` if no alias applies.

    E.g.::

        "@/lib/db"  →  "src.lib.db"   (when @/* -> ["./src/*"])
        "@/lib/db"  →  None            (when no mapping present)

    The returned string uses dots (``src.lib.db``) so it integrates
    directly with the existing resolver's dotted-qualname lookup.
    """
    if mapping.is_empty():
        return None

    for pattern_key, replacements in mapping.paths.items():
        if not replacements:
            continue
        replacement = replacements[0]  # tsconfig resolves first match

        if pattern_key.endswith("/*"):
            prefix = pattern_key[:-2]   # e.g. "@"
            if import_target.startswith(prefix + "/"):
                suffix = import_target[len(prefix) + 1:]  # after the "/"
                # Build the resolved path: replacement is e.g. "./src/*"
                repl_base = replacement[:-2] if replacement.endswith("/*") \
                    else replacement
                # Strip leading "./" or "../" relative prefix
                repl_base = repl_base.lstrip(".")
                repl_base = repl_base.lstrip("/")
                # Combine: "src" + "/" + "lib/db" -> "src/lib/db"
                combined = (repl_base.rstrip("/") + "/" + suffix).lstrip("/")
                return combined.replace("/", ".")
        else:
            # Exact match (no wildcard)
            if import_target == pattern_key:
                repl = replacement
                repl = repl.lstrip("./")
                return repl.replace("/", ".")

    # baseUrl fallback: bare non-relative non-alias imports resolve relative
    # to baseUrl directory (e.g. "lib/db" -> baseUrl/lib/db).
    if mapping.base_url is not None and not import_target.startswith(".") \
            and not import_target.startswith("@"):
        # Only attempt if we haven't matched an alias above.
        # Convert to dotted qualname relative to repo_root.
        try:
            rel = mapping.base_url.relative_to(repo_root)
            prefix = str(rel).replace("/", ".")
            dotted = import_target.replace("/", ".")
            return f"{prefix}.{dotted}" if prefix else dotted
        except ValueError:
            pass

    return None
