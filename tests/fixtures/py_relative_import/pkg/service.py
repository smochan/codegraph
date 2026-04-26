"""Service that uses a relative import of Foo."""
from __future__ import annotations

from .models import Foo


def make_foo() -> Foo:
    return Foo()
