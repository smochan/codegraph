"""Flask-style HTTP routes — used as HANDLER fixtures."""
from __future__ import annotations


class _AppStub:
    def route(self, path: str):
        def deco(f):
            return f
        return deco


app = _AppStub()


@app.route("/")
def index() -> str:
    return "hello"
