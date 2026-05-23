"""Realistic-Claude-Code-baseline MCP server.

Exposes a minimal file-system surface — read_file, grep, list_directory —
that mimics what Claude Code, Cursor, and Windsurf give their host LLM out
of the box. This is the *real* baseline polycodegraph competes against,
not "Claude with no tools at all".

Run as: `python -m bench.runners.filetools_mcp`  (stdio transport)
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("filetools")

# All operations are confined to cwd at process start. The harness spawns this
# server with cwd=<target repo>, so reads can't escape the benchmark target.
ROOT = Path.cwd().resolve()
MAX_FILE_BYTES = 1_000_000        # 1 MB hard cap per read
DEFAULT_READ_LIMIT = 2000          # default lines returned by read_file
MAX_GREP_HITS = 200                # cap on grep results to keep payloads sane


def _safe(path: str) -> Path:
    """Resolve path under ROOT or raise ValueError. No symlink escapes."""
    p = (ROOT / path).resolve()
    if ROOT not in p.parents and p != ROOT:
        raise ValueError(f"path {path!r} escapes benchmark root")
    return p


@mcp.tool()
def read_file(path: str, offset: int = 1, limit: int = DEFAULT_READ_LIMIT) -> str:
    """Read a file's contents.

    Args:
        path: file path relative to the repo root.
        offset: 1-indexed starting line (default 1 = start of file).
        limit: max lines to return (default 2000).

    Returns:
        The file contents joined by newline, prefixed with one header line:
        "<path>  (lines <offset>-<end>, <total> total)".
    """
    p = _safe(path)
    if not p.is_file():
        return f"error: {path!r} is not a file"
    if p.stat().st_size > MAX_FILE_BYTES:
        return f"error: {path!r} exceeds {MAX_FILE_BYTES} byte cap"
    text = p.read_text(errors="replace")
    lines = text.splitlines()
    total = len(lines)
    start = max(1, offset) - 1
    end = min(total, start + limit)
    body = "\n".join(lines[start:end])
    header = f"{path}  (lines {start + 1}-{end}, {total} total)"
    return f"{header}\n{body}"


@mcp.tool()
def grep(
    pattern: str,
    path: str = ".",
    case_insensitive: bool = False,
    include: str = "",
) -> str:
    """Search file contents for a regex pattern.

    Args:
        pattern: regex pattern to search for.
        path: file or directory to search under (default: repo root).
        case_insensitive: if True, ignore case.
        include: glob to restrict the file extensions, e.g. "*.py".

    Returns:
        Lines of `relative_path:line_number:text`, capped at MAX_GREP_HITS.
        Falls back to pure Python re if ripgrep (`rg`) is not installed.
    """
    p = _safe(path)
    rg = shutil.which("rg")
    if rg:
        return _grep_rg(rg, pattern, p, case_insensitive, include)
    return _grep_python(pattern, p, case_insensitive, include)


def _grep_rg(rg: str, pattern: str, target: Path, ignore_case: bool, include: str) -> str:
    args = [rg, "--line-number", "--no-heading", "--color=never", "-uu"]
    if ignore_case:
        args.append("-i")
    if include:
        args += ["--glob", include]
    args += ["-e", pattern, str(target)]
    try:
        res = subprocess.run(args, capture_output=True, text=True, timeout=20)
    except subprocess.TimeoutExpired:
        return "error: grep timed out at 20s"
    lines = res.stdout.splitlines()[:MAX_GREP_HITS]
    rel = []
    for ln in lines:
        # Normalize absolute paths in rg output back to repo-relative.
        if ln.startswith(str(ROOT) + os.sep):
            rel.append(ln[len(str(ROOT)) + 1:])
        else:
            rel.append(ln)
    suffix = "" if len(rel) < MAX_GREP_HITS else f"\n... (truncated at {MAX_GREP_HITS} hits)"
    return ("\n".join(rel) or "no matches") + suffix


def _grep_python(pattern: str, target: Path, ignore_case: bool, include: str) -> str:
    flags = re.IGNORECASE if ignore_case else 0
    try:
        rx = re.compile(pattern, flags)
    except re.error as exc:
        return f"error: bad regex: {exc}"
    hits: list[str] = []
    paths = [target] if target.is_file() else target.rglob(include or "*")
    for p in paths:
        if not p.is_file():
            continue
        try:
            for i, line in enumerate(p.read_text(errors="replace").splitlines(), 1):
                if rx.search(line):
                    rel = p.relative_to(ROOT)
                    hits.append(f"{rel}:{i}:{line}")
                    if len(hits) >= MAX_GREP_HITS:
                        break
        except (OSError, UnicodeDecodeError):
            continue
        if len(hits) >= MAX_GREP_HITS:
            break
    suffix = "" if len(hits) < MAX_GREP_HITS else f"\n... (truncated at {MAX_GREP_HITS} hits)"
    return ("\n".join(hits) or "no matches") + suffix


@mcp.tool()
def list_directory(path: str = ".") -> str:
    """List immediate children of a directory.

    Args:
        path: directory path relative to repo root (default: repo root).

    Returns:
        Lines of "<type>  <name>" where type is "d" (dir) or "f" (file).
        Hidden entries (dot-prefixed) and common noise (__pycache__, .git, etc.)
        are skipped.
    """
    p = _safe(path)
    if not p.is_dir():
        return f"error: {path!r} is not a directory"
    skip = {".git", ".venv", ".venvs", "node_modules", "__pycache__", ".codegraph"}
    out: list[str] = []
    for child in sorted(p.iterdir()):
        if child.name in skip or child.name.startswith("."):
            continue
        kind = "d" if child.is_dir() else "f"
        out.append(f"{kind}  {child.name}")
    return "\n".join(out) if out else "empty directory"


if __name__ == "__main__":
    mcp.run()
