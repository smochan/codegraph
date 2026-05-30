"""LRU pruning for `.codegraph/explore/` and similar generated caches.

`codegraph serve` regenerates pyvis HTML per explored function and never
prunes; long-lived projects can grow this to hundreds of MB. This
module gives us a single helper that evicts oldest-mtime files until
the total size is under a cap, plus a CLI-friendly size reporter.
"""
from __future__ import annotations

import contextlib
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class PruneResult:
    files_deleted: int
    bytes_freed: int
    bytes_remaining: int


def directory_size_bytes(path: Path) -> int:
    """Total size in bytes of all files under *path* (recursive)."""
    if not path.exists():
        return 0
    total = 0
    for p in path.rglob("*"):
        try:
            if p.is_file():
                total += p.stat().st_size
        except OSError:
            continue
    return total


def prune_cache_to_size(
    path: Path, max_size_mb: float
) -> PruneResult:
    """Evict files by oldest mtime until total size is under *max_size_mb*.

    Files are ranked by mtime ascending (oldest first). Empty
    directories left behind by the prune are removed. Subdirectories
    are walked recursively.

    Symlinks and non-file entries are ignored. ``max_size_mb`` is the
    soft cap; the final size may be below it.
    """
    if not path.exists() or not path.is_dir():
        return PruneResult(0, 0, 0)

    files: list[tuple[float, int, Path]] = []
    for p in path.rglob("*"):
        try:
            if not p.is_file() or p.is_symlink():
                continue
            stat = p.stat()
            files.append((stat.st_mtime, stat.st_size, p))
        except OSError:
            continue

    total = sum(size for _mtime, size, _p in files)
    cap = int(max_size_mb * 1024 * 1024)
    if total <= cap:
        return PruneResult(0, 0, total)

    # Oldest first.
    files.sort(key=lambda t: t[0])
    deleted = 0
    freed = 0
    for _mtime, size, victim in files:
        if total <= cap:
            break
        try:
            victim.unlink()
        except OSError:
            continue
        deleted += 1
        freed += size
        total -= size

    # Sweep empty subdirs left behind.
    for sub in sorted(path.rglob("*"), key=lambda p: -len(p.parts)):
        if sub.is_dir():
            try:
                next(sub.iterdir())
            except StopIteration:
                with contextlib.suppress(OSError):
                    sub.rmdir()

    return PruneResult(
        files_deleted=deleted, bytes_freed=freed, bytes_remaining=total
    )
