"""Tests for core (v1)."""
from __future__ import annotations

from core import helper_a, helper_b


def test_helper_a() -> None:
    assert helper_a(1) == 2


def test_helper_b() -> None:
    assert helper_b(1) == 3
