"""Fixture exercising the public-API pragma forms."""
from __future__ import annotations


# pragma: codegraph-public-api
def marked_function() -> int:
    return 1


# codegraph: public-api
def alt_marked_function() -> int:
    return 2


def unmarked_function() -> int:
    return 3


# pragma: codegraph-public-api
@staticmethod
def decorated_marked() -> int:
    """Pragma sits above the decorator stack."""
    return 4


# pragma: foo
def looks_like_pragma() -> int:
    """Random pragma-like comment that is not the public-api one."""
    return 5


# pragma: codegraph-public-api
class MarkedClass:
    """Class-level pragma exempts the class itself but not its methods."""

    def regular_method(self) -> int:
        return 1

    # pragma: codegraph-public-api
    def marked_method(self) -> int:
        return 2

    def unmarked_method(self) -> int:
        return 3
