"""Tests for `cache_prune` (v0.1.2 #6)."""
from __future__ import annotations

import os
import time
from pathlib import Path

from codegraph.cache_prune import (
    directory_size_bytes,
    prune_cache_to_size,
)


def _make_file(path: Path, size_bytes: int, mtime: float | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x" * size_bytes)
    if mtime is not None:
        os.utime(path, (mtime, mtime))


def test_directory_size_handles_missing_path(tmp_path: Path) -> None:
    assert directory_size_bytes(tmp_path / "nope") == 0


def test_directory_size_sums_all_files(tmp_path: Path) -> None:
    _make_file(tmp_path / "a.html", 100)
    _make_file(tmp_path / "sub" / "b.html", 200)
    assert directory_size_bytes(tmp_path) == 300


def test_prune_returns_zero_when_under_cap(tmp_path: Path) -> None:
    _make_file(tmp_path / "a.html", 1000)
    result = prune_cache_to_size(tmp_path, max_size_mb=1.0)  # 1 MB cap
    assert result.files_deleted == 0
    assert result.bytes_freed == 0
    assert result.bytes_remaining == 1000


def test_prune_evicts_oldest_first(tmp_path: Path) -> None:
    now = time.time()
    _make_file(tmp_path / "old.html", 600_000, mtime=now - 1000)
    _make_file(tmp_path / "mid.html", 600_000, mtime=now - 500)
    _make_file(tmp_path / "new.html", 600_000, mtime=now)
    # Cap = 1 MB. Total = ~1.8 MB. Need to evict ~0.8 MB; the oldest
    # 600KB file goes first; that leaves ~1.2 MB which is still over
    # cap, so the next-oldest gets evicted too.
    result = prune_cache_to_size(tmp_path, max_size_mb=1.0)
    assert result.files_deleted == 2
    assert not (tmp_path / "old.html").exists()
    assert not (tmp_path / "mid.html").exists()
    assert (tmp_path / "new.html").exists()


def test_prune_removes_empty_subdirs(tmp_path: Path) -> None:
    _make_file(tmp_path / "sub" / "a.html", 2_000_000, mtime=0)
    _make_file(tmp_path / "keep.html", 100)
    prune_cache_to_size(tmp_path, max_size_mb=0.001)
    assert not (tmp_path / "sub").exists()


def test_prune_max_size_zero_wipes_everything(tmp_path: Path) -> None:
    _make_file(tmp_path / "a.html", 100, mtime=1.0)
    _make_file(tmp_path / "b.html", 100, mtime=2.0)
    result = prune_cache_to_size(tmp_path, max_size_mb=0.0)
    assert result.files_deleted == 2
    assert result.bytes_remaining == 0


def test_prune_no_op_on_nonexistent_dir(tmp_path: Path) -> None:
    result = prune_cache_to_size(tmp_path / "nope", max_size_mb=1.0)
    assert result.files_deleted == 0
    assert result.bytes_remaining == 0
