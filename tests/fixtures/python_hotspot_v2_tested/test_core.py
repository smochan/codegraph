"""Tests for core (v2) — this variant DOES test hot_helper directly."""
from __future__ import annotations

from core import helper_a, helper_b, hot_helper


def test_hot_helper() -> None:
    assert hot_helper(2) == 20


def test_helper_a() -> None:
    assert helper_a(1) == 11


def test_helper_b() -> None:
    assert helper_b(1) == 12
