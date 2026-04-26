"""Pytest fixture file for entry-point detection."""
import pytest


@pytest.fixture
def db_connection() -> dict[str, bool]:
    return {"connected": True}


@pytest.fixture(scope="session")
def app_client() -> object:
    return object()


@pytest.mark.slow
def regression_check() -> bool:
    return True


def _setup_db() -> None:
    pass
