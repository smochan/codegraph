"""Lightweight stdlib HTTP server for the codegraph dashboard."""
from __future__ import annotations

import datetime as dt
import importlib.resources as resources
import json
import logging
import mimetypes
import threading
import webbrowser
from collections.abc import Callable
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import networkx as nx

from codegraph.viz.dashboard import build_dashboard_payload

logger = logging.getLogger(__name__)

_STATIC_PKG = "codegraph.web.static"


def _read_static(name: str) -> bytes:
    return (resources.files(_STATIC_PKG) / name).read_bytes()


class DashboardState:
    """Holds the rebuildable graph + cached payload."""

    def __init__(
        self,
        repo_root: Path,
        explore_dir: Path,
        graph_loader: Callable[[], nx.MultiDiGraph],
        rebuild: Callable[[], nx.MultiDiGraph] | None = None,
    ) -> None:
        self.repo_root = repo_root
        self.explore_dir = explore_dir
        self._graph_loader = graph_loader
        self._rebuild = rebuild
        self._lock = threading.Lock()
        self._payload: dict[str, Any] | None = None

    def payload(self) -> dict[str, Any]:
        with self._lock:
            if self._payload is None:
                self._payload = self._build_payload(self._graph_loader())
            return self._payload

    def rebuild(self) -> dict[str, Any]:
        with self._lock:
            graph = (
                self._graph_loader() if self._rebuild is None else self._rebuild()
            )
            self._payload = self._build_payload(graph)
            return self._payload

    def _build_payload(self, graph: nx.MultiDiGraph) -> dict[str, Any]:
        payload = build_dashboard_payload(graph)
        payload["repo"] = self.repo_root.name
        payload["built_at"] = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        return payload


class _Handler(BaseHTTPRequestHandler):
    state: DashboardState  # set per-instance via factory

    def log_message(self, format: str, *args: Any) -> None:
        logger.debug("%s - %s", self.address_string(), format % args)

    # ---- helpers ----
    def _send_bytes(
        self, body: bytes, content_type: str, status: int = 200
    ) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _send_json(self, data: dict[str, Any], status: int = 200) -> None:
        body = json.dumps(data).encode("utf-8")
        self._send_bytes(body, "application/json; charset=utf-8", status)

    def _not_found(self) -> None:
        self._send_bytes(b"not found", "text/plain", HTTPStatus.NOT_FOUND)

    # ---- routes ----
    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/" or path == "/index.html":
            self._send_bytes(_read_static("index.html"),
                             "text/html; charset=utf-8")
            return
        if path == "/api/data.json":
            self._send_json(self.state.payload())
            return
        if path.startswith("/static/"):
            name = path[len("/static/"):]
            try:
                data = _read_static(name)
            except (FileNotFoundError, ModuleNotFoundError):
                self._not_found()
                return
            ctype, _ = mimetypes.guess_type(name)
            self._send_bytes(data, ctype or "application/octet-stream")
            return
        # Anything else: try the explore dir for pyvis pages.
        candidate = self.state.explore_dir / path.lstrip("/")
        try:
            candidate = candidate.resolve()
            candidate.relative_to(self.state.explore_dir.resolve())
        except (ValueError, OSError):
            self._not_found()
            return
        if candidate.is_file():
            ctype, _ = mimetypes.guess_type(str(candidate))
            self._send_bytes(candidate.read_bytes(),
                             ctype or "application/octet-stream")
            return
        self._not_found()

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        if path == "/api/rebuild":
            try:
                self.state.rebuild()
            except Exception as exc:
                logger.exception("rebuild failed")
                self._send_json({"error": str(exc)}, status=500)
                return
            self._send_json({"ok": True})
            return
        self._not_found()


def serve(
    state: DashboardState,
    *,
    host: str = "127.0.0.1",
    port: int = 8765,
    open_browser: bool = True,
) -> None:
    """Block on the dashboard HTTP server."""
    handler_cls = type("_BoundHandler", (_Handler,), {"state": state})
    server = ThreadingHTTPServer((host, port), handler_cls)
    url = f"http://{host}:{port}/"
    print(f"\n  codegraph dashboard ready at \033[36m{url}\033[0m")
    print("  press Ctrl+C to stop\n")
    if open_browser:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n  shutting down...")
    finally:
        server.shutdown()


__all__ = ["DashboardState", "serve"]
