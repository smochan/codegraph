"""Tests for models (v2 - no longer references removed Dog.fetch)."""
from __future__ import annotations

from models import Cat, Dog


def test_dog_speaks() -> None:
    dog = Dog("Rex")
    result = dog.speak()
    assert "Rex" in result


def test_cat_speaks() -> None:
    cat = Cat("Whiskers")
    assert "Whiskers" in cat.speak()
