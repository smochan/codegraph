"""FastAPI-style HTTP routes — used as HANDLER fixtures."""
from __future__ import annotations


class _AppStub:
    def get(self, path: str):
        def deco(f):
            return f
        return deco

    def post(self, path: str):
        def deco(f):
            return f
        return deco


app = _AppStub()


@app.get("/health")
def health_check() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/items")
def create_item(payload: dict) -> dict:
    return payload
