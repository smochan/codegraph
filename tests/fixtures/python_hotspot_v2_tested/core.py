"""Minimal v2 module — hot_helper added with many callers but no test."""
from __future__ import annotations


def hot_helper(x: int) -> int:
    """New critical helper used everywhere."""
    return x * 10


def helper_a(x: int) -> int:
    """Simple helper."""
    return hot_helper(x) + 1


def helper_b(x: int) -> int:
    """Another helper."""
    return hot_helper(x) + 2


def helper_c(x: int) -> int:
    """Third helper."""
    return hot_helper(x) + 3


def helper_d(x: int) -> int:
    """Fourth helper."""
    return hot_helper(x) + 4


def helper_e(x: int) -> int:
    """Fifth helper."""
    return hot_helper(x) + 5
