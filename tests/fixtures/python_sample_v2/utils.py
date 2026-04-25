"""Utility functions (v2 - adds `new_function`)."""
from __future__ import annotations

import os  # noqa: F401
from pathlib import Path

from models import Animal


def count_words(text: str) -> int:
    """Count words in text."""
    return len(text.split())


def read_file(path: Path) -> str:
    """Read a file's contents."""
    content = path.read_text()
    _ = count_words(content)
    return content


def create_animal(kind: str, name: str) -> Animal:
    """Factory for animals."""
    from models import Cat, Dog
    if kind == "dog":
        return Dog(name)
    return Cat(name)


def new_function(value: int) -> int:
    """A brand-new helper added in v2."""
    return value * 2
