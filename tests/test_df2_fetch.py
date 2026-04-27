"""DF2 tests: FETCH_CALL extraction from TS / TSX / JS files.

The DF2 extractor walks function and method bodies and emits a FETCH_CALL
edge for every recognised HTTP call site (fetch / axios / SWR / TanStack /
generic api-client). The synthetic destination node carries a stable
``fetch::<METHOD>::<URL>`` id; edges carry ``method``/``url``/``library``
and best-effort ``body_keys``.
"""
from __future__ import annotations

from pathlib import Path

import networkx as nx
import pytest

from codegraph.graph.schema import Edge, EdgeKind, Node
from codegraph.parsers.typescript import TypeScriptExtractor
from codegraph.viz.hld import build_hld, serialize_fetch_edges

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "df2_fetch"


@pytest.fixture(scope="module")
def parsed() -> tuple[list[Node], list[Edge]]:
    extractor = TypeScriptExtractor()
    return extractor.parse_file(FIXTURE_DIR / "sample.ts", FIXTURE_DIR)


def _fetches_from(edges: list[Edge]) -> list[Edge]:
    return [e for e in edges if e.kind == EdgeKind.FETCH_CALL]


def _by_url(edges: list[Edge], url: str) -> list[Edge]:
    return [
        e for e in _fetches_from(edges) if e.metadata.get("url") == url
    ]


def test_fetch_get_emits_method_get_library_fetch(
    parsed: tuple[list[Node], list[Edge]],
) -> None:
    _, edges = parsed
    hits = _by_url(edges, "/api/items")
    assert any(
        e.metadata["method"] == "GET" and e.metadata["library"] == "fetch"
        for e in hits
    )


def test_fetch_post_emits_method_post(
    parsed: tuple[list[Node], list[Edge]],
) -> None:
    _, edges = parsed
    # /api/items has both GET (getItems) and POST (postItem) — find POST.
    hits = _by_url(edges, "/api/items")
    posts = [e for e in hits if e.metadata["method"] == "POST"]
    assert posts, "expected POST fetch to /api/items"
    assert posts[0].metadata["library"] == "fetch"


def test_fetch_post_extracts_body_keys_from_json_stringify(
    parsed: tuple[list[Node], list[Edge]],
) -> None:
    _, edges = parsed
    posts = [
        e for e in _by_url(edges, "/api/items")
        if e.metadata["method"] == "POST" and e.metadata["library"] == "fetch"
    ]
    assert posts
    assert posts[0].metadata["body_keys"] == ["name", "email"]


def test_axios_get_emits_axios_library(
    parsed: tuple[list[Node], list[Edge]],
) -> None:
    _, edges = parsed
    hits = _by_url(edges, "/api/items")
    axios_get = [
        e for e in hits
        if e.metadata["library"] == "axios" and e.metadata["method"] == "GET"
    ]
    assert axios_get


def test_axios_post_extracts_body_keys(
    parsed: tuple[list[Node], list[Edge]],
) -> None:
    _, edges = parsed
    hits = _by_url(edges, "/api/items")
    axios_post = [
        e for e in hits
        if e.metadata["library"] == "axios" and e.metadata["method"] == "POST"
    ]
    assert axios_post
    assert axios_post[0].metadata["body_keys"] == ["name"]


def test_axios_config_call_extracts_method_and_url(
    parsed: tuple[list[Node], list[Edge]],
) -> None:
    _, edges = parsed
    hits = _by_url(edges, "/api/x")
    assert hits
    assert hits[0].metadata["method"] == "PUT"
    assert hits[0].metadata["library"] == "axios"


def test_useswr_treated_as_get_swr_library(
    parsed: tuple[list[Node], list[Edge]],
) -> None:
    _, edges = parsed
    swr = [
        e for e in _fetches_from(edges)
        if e.metadata["library"] == "swr"
    ]
    assert swr
    assert swr[0].metadata["method"] == "GET"
    assert swr[0].metadata["url"] == "/api/items"


def test_apiclient_delete_emits_apiclient_library(
    parsed: tuple[list[Node], list[Edge]],
) -> None:
    _, edges = parsed
    hits = _by_url(edges, "/api/items/1")
    assert hits
    assert hits[0].metadata["method"] == "DELETE"
    assert hits[0].metadata["library"] == "apiclient"


def test_template_url_captured_verbatim(
    parsed: tuple[list[Node], list[Edge]],
) -> None:
    _, edges = parsed
    template = [
        e for e in _fetches_from(edges)
        if e.metadata.get("url_kind") == "template"
    ]
    assert template, "expected at least one template-literal fetch"
    assert "${id}" in template[0].metadata["url"]


def test_dynamic_url_marked_dynamic(
    parsed: tuple[list[Node], list[Edge]],
) -> None:
    _, edges = parsed
    dynamic = [
        e for e in _fetches_from(edges)
        if e.metadata.get("url_kind") == "dynamic"
    ]
    assert dynamic, "expected fetch(url) to emit url_kind=dynamic"
    assert dynamic[0].metadata["library"] == "fetch"


def test_multiple_fetches_each_emit_their_own_edge(
    parsed: tuple[list[Node], list[Edge]],
) -> None:
    _, edges = parsed
    a = _by_url(edges, "/api/a")
    b = _by_url(edges, "/api/b")
    c = _by_url(edges, "/api/c")
    assert len(a) == 1
    assert len(b) == 1
    assert len(c) == 1
    # All three share the same enclosing function (multiCalls).
    assert {e.src for e in a + b + c} == {a[0].src}


def test_tsx_component_fetch_emits_edge() -> None:
    extractor = TypeScriptExtractor()
    _, edges = extractor.parse_file(
        FIXTURE_DIR / "Component.tsx", FIXTURE_DIR
    )
    fetches = _fetches_from(edges)
    assert fetches
    assert fetches[0].metadata["url"] == "/api/items"
    assert fetches[0].metadata["library"] == "fetch"


def test_top_level_fetch_is_silently_skipped(
    parsed: tuple[list[Node], list[Edge]],
) -> None:
    _, edges = parsed
    # The top-level `fetch("/api/top-level-skip")` is outside any function;
    # the parser visits only function/method bodies, so no edge should fire.
    assert not _by_url(edges, "/api/top-level-skip")


def test_hld_payload_fetches_populated() -> None:
    extractor = TypeScriptExtractor()
    nodes, edges = extractor.parse_file(
        FIXTURE_DIR / "sample.ts", FIXTURE_DIR
    )
    g: nx.MultiDiGraph = nx.MultiDiGraph()
    for n in nodes:
        g.add_node(
            n.id,
            kind=n.kind.value,
            qualname=n.qualname,
            name=n.name,
            file=n.file,
            line_start=n.line_start,
            metadata=n.metadata,
        )
    for e in edges:
        g.add_edge(
            e.src, e.dst, key=e.kind.value, kind=e.kind.value,
            metadata=e.metadata,
        )

    fetches = serialize_fetch_edges(g)
    assert fetches, "expected serialize_fetch_edges to populate entries"
    sample = fetches[0]
    assert {"caller_qn", "method", "url", "library", "body_keys"} <= sample.keys()

    payload = build_hld(g)
    assert payload.fetches == fetches
