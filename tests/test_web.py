"""Smoke tests for the codegraph web dashboard server."""
from __future__ import annotations

import json
import re
import threading
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import networkx as nx
import pytest

from codegraph.viz.dashboard import build_dashboard_payload
from codegraph.web.server import DashboardState, _Handler


def _tiny_graph() -> nx.MultiDiGraph:
    g: nx.MultiDiGraph = nx.MultiDiGraph()
    g.add_node("a.py:foo", kind="function", file="a.py", qualname="a.foo",
               name="foo", language="python", loc=3)
    g.add_node("b.py:bar", kind="function", file="b.py", qualname="b.bar",
               name="bar", language="python", loc=2)
    g.add_edge("a.py:foo", "b.py:bar", kind="CALLS")
    return g


def test_build_dashboard_payload_keys() -> None:
    payload = build_dashboard_payload(_tiny_graph())
    for key in ("metrics", "issues", "hotspots", "matrix", "sankey",
                "treemap", "flows", "files", "hld"):
        assert key in payload
    assert payload["metrics"]["nodes"] == 2
    assert payload["metrics"]["edges"] == 1


@pytest.fixture
def server(tmp_path: Path) -> tuple[ThreadingHTTPServer, str]:
    state = DashboardState(
        repo_root=tmp_path,
        explore_dir=tmp_path / "explore",
        graph_loader=_tiny_graph,
    )
    handler_cls = type("_TestHandler", (_Handler,), {"state": state})
    srv = ThreadingHTTPServer(("127.0.0.1", 0), handler_cls)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    yield srv, base
    srv.shutdown()


def test_serves_index(server: tuple[ThreadingHTTPServer, str]) -> None:
    _, base = server
    with urllib.request.urlopen(f"{base}/") as resp:
        assert resp.status == 200
        body = resp.read().decode("utf-8")
    assert "<html" in body.lower()


def test_api_data(server: tuple[ThreadingHTTPServer, str]) -> None:
    _, base = server
    with urllib.request.urlopen(f"{base}/api/data.json") as resp:
        data = json.loads(resp.read())
    assert data["metrics"]["nodes"] == 2
    assert data["repo"]  # repo name attached by server


def test_path_traversal_blocked(server: tuple[ThreadingHTTPServer, str]) -> None:
    _, base = server
    req = urllib.request.Request(f"{base}/../../etc/passwd")
    try:
        urllib.request.urlopen(req)
    except urllib.error.HTTPError as exc:
        assert exc.code == 404
    else:
        pytest.fail("expected 404")


def test_rebuild_endpoint(server: tuple[ThreadingHTTPServer, str]) -> None:
    _, base = server
    req = urllib.request.Request(f"{base}/api/rebuild", method="POST", data=b"")
    with urllib.request.urlopen(req) as resp:
        data = json.loads(resp.read())
    assert data == {"ok": True}


# ---------------------------------------------------------------------------
# Offline / local-first enforcement
# ---------------------------------------------------------------------------

#: CDN hostnames that must NOT appear in vendored static assets.
_CDN_PATTERN = re.compile(
    r"https?://"
    r"(unpkg\.com"
    r"|esm\.sh"
    r"|cdn\.tailwindcss\.com"
    r"|cdn\.jsdelivr\.net"
    r"|rsms\.me"
    r"|fonts\.googleapis\.com"
    r"|fonts\.gstatic\.com"
    r"|d3js\.org)"
)

#: Static files to scan (relative to the static root, excluding vendor/).
_STATIC_ROOT = Path(__file__).parent.parent / "codegraph" / "web" / "static"
_SCAN_GLOBS = ["*.html", "*.js", "*.css", "views/*.html", "views/*.js", "views/*.css"]


def _collect_static_files() -> list[Path]:
    """Return HTML/JS/CSS files under codegraph/web/static/ (excluding vendor/)."""
    files: list[Path] = []
    for pattern in _SCAN_GLOBS:
        files.extend(_STATIC_ROOT.glob(pattern))
    return sorted(set(files))


def test_no_cdn_references() -> None:
    """Assert that no CDN URLs survive in non-vendor static assets.

    vendor/README.md is the authoritative manifest of vendored libraries and is
    the only file permitted to reference CDN URLs (as documentation).  All other
    HTML/JS/CSS files must reference /static/vendor/* local paths only.
    """
    violations: list[str] = []
    for path in _collect_static_files():
        text = path.read_text(encoding="utf-8", errors="replace")
        for match in _CDN_PATTERN.finditer(text):
            line_no = text.count("\n", 0, match.start()) + 1
            violations.append(f"{path.relative_to(_STATIC_ROOT)}:{line_no}: {match.group(0)}")

    if violations:
        joined = "\n  ".join(violations)
        raise AssertionError(
            f"CDN references found in static assets (offline local-first violated):\n  {joined}"
        )


def test_vendor_files_present() -> None:
    """Assert that the key vendored library files exist on disk."""
    vendor = _STATIC_ROOT / "vendor"
    required = [
        "d3.v7.min.js",
        "d3-sankey@0.12.3.min.js",
        "mermaid@10.9.1.min.js",
        "lucide@0.414.0.min.js",
        "3d-force-graph@1.min.js",
        "three-spritetext@1.10.0.mjs",
        "fonts.css",
        "fonts/InterVariable.woff2",
        "fonts/JetBrainsMono-400-latin.woff2",
    ]
    missing = [f for f in required if not (vendor / f).exists()]
    assert not missing, f"Vendored files missing: {missing}"
