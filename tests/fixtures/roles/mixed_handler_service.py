"""A SERVICE class that also exposes an HTTP HANDLER method.

The handler method must keep its HANDLER role even though the enclosing
class is a SERVICE.
"""
from __future__ import annotations


class _RouterStub:
    def get(self, path: str):
        def deco(f):
            return f
        return deco


router = _RouterStub()


class ReportService:
    @router.get("/reports")
    def list_reports(self) -> list[dict]:
        return []

    def build_report(self) -> dict:
        return {}
