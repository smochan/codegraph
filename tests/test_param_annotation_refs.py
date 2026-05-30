"""Tests for parameter-annotation REFERENCES (v0.1.2 #3).

A FastAPI handler that takes a Pydantic model as a body parameter used
to look like dead code: the model class had no incoming CALLS / IMPORTS
/ INHERITS / IMPLEMENTS edges because the only "reference" was a type
annotation on the handler's parameter, which the parser didn't trace.
This module verifies the fix: handlers emit ``CALLS`` edges from the
handler to each capitalized type name in their parameter and return
type annotations, with ``metadata.via == "annotation"``.
"""
from __future__ import annotations

from pathlib import Path

import networkx as nx
import pytest

from codegraph.analysis import find_dead_code
from codegraph.graph.builder import GraphBuilder
from codegraph.graph.store_networkx import to_digraph
from codegraph.graph.store_sqlite import SQLiteGraphStore
from codegraph.parsers.python import _extract_type_references


def test_extract_type_references_simple() -> None:
    assert _extract_type_references("User") == ["User"]
    assert _extract_type_references("str") == []  # not capitalized
    assert _extract_type_references(None) == []
    assert _extract_type_references("") == []


def test_extract_type_references_generic_and_union() -> None:
    assert _extract_type_references("list[User]") == ["User"]
    assert _extract_type_references("dict[str, User]") == ["User"]
    assert _extract_type_references("User | None") == ["User"]
    assert _extract_type_references("Optional[User]") == ["User"]
    assert _extract_type_references("Annotated[User, Body(...)]") == ["User"]


def test_extract_type_references_drops_typing_scaffolding() -> None:
    # All of these are blocklisted; only `User` should survive.
    ann = "Annotated[Optional[Union[User, Admin]], Body(...)]"
    assert set(_extract_type_references(ann)) == {"User", "Admin"}


def test_extract_type_references_deduplicates_in_order() -> None:
    assert _extract_type_references("dict[User, User]") == ["User"]
    assert _extract_type_references("tuple[A, B, A]") == ["A", "B"]


@pytest.fixture
def fastapi_repo_graph(tmp_path: Path) -> nx.MultiDiGraph:
    """Tiny FastAPI-style fixture: a handler that takes a Pydantic body."""
    repo = tmp_path / "repo"
    (repo / "myapp").mkdir(parents=True)
    (repo / "myapp" / "__init__.py").write_text("")
    (repo / "myapp" / "models.py").write_text(
        "class RetroDefect:\n"
        "    name: str\n"
    )
    (repo / "myapp" / "routes.py").write_text(
        "from myapp.models import RetroDefect\n"
        "\n"
        "def app_get(path):\n"
        "    def deco(fn): return fn\n"
        "    return deco\n"
        "\n"
        "@app_get('/defect')\n"
        "def create_defect(body: RetroDefect) -> RetroDefect:\n"
        "    return body\n"
    )
    store = SQLiteGraphStore(tmp_path / "graph.db")
    GraphBuilder(repo, store).build(incremental=False)
    g = to_digraph(store)
    store.close()
    return g


def test_pydantic_model_not_dead_when_only_referenced_via_annotation(
    fastapi_repo_graph: nx.MultiDiGraph,
) -> None:
    dead_qns = {d.qualname for d in find_dead_code(fastapi_repo_graph)}
    assert not any(qn.endswith("RetroDefect") for qn in dead_qns), (
        "RetroDefect is referenced by the handler's body+return annotations "
        "and must not be flagged dead. dead_qns=" + repr(dead_qns)
    )


def test_handler_has_annotation_edge_to_model(
    fastapi_repo_graph: nx.MultiDiGraph,
) -> None:
    """The handler should have an outgoing edge tagged via=annotation."""
    g = fastapi_repo_graph
    found_via_annotation = False
    for src, _dst, _key, data in g.edges(keys=True, data=True):
        attrs = g.nodes.get(src) or {}
        if not str(attrs.get("qualname") or "").endswith("create_defect"):
            continue
        md = data.get("metadata") or {}
        if isinstance(md, dict) and md.get("via") == "annotation":
            found_via_annotation = True
            break
    assert found_via_annotation, "expected an annotation-via edge from handler"
