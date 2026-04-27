"""Repository classes used as REPO fixtures."""
from __future__ import annotations


class OrderRepository:
    def find_by_id(self, oid: str) -> dict | None:
        return {"id": oid}

    def save(self, order: dict) -> dict:
        return order
