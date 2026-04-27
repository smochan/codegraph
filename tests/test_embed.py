"""Tests for the v0.3 embeddings layer."""
from __future__ import annotations

import hashlib
import math
import shutil
from pathlib import Path
from typing import Any

import networkx as nx
import pytest
from typer.testing import CliRunner

from codegraph.cli import app
from codegraph.embed.chunker import Chunk, chunk_repo
from codegraph.embed.embedder import DEFAULT_DIM, Embedder
from codegraph.embed.query import (
    IndexMissingError,
    hybrid_query,
    semantic_query,
)
from codegraph.embed.store import EmbeddingStore, StoredChunk, build_index
from codegraph.graph.builder import GraphBuilder
from codegraph.graph.schema import NodeKind
from codegraph.graph.store_networkx import to_digraph
from codegraph.graph.store_sqlite import SQLiteGraphStore

FIXTURES = Path(__file__).parent / "fixtures"


# ---------------------------------------------------------------------------
# Fake encoder — deterministic, dependency-free
# ---------------------------------------------------------------------------


class _FakeEncoder:
    """Hash-based fake that mimics the SentenceTransformer.encode interface."""

    def __init__(self, dim: int = 32) -> None:
        self.dim = dim
        self.calls = 0

    def encode(
        self,
        sentences: list[str],
        *,
        batch_size: int = 32,
        show_progress_bar: bool = False,
        convert_to_numpy: bool = True,
        normalize_embeddings: bool = True,
    ) -> Any:
        self.calls += 1
        out: list[list[float]] = []
        for s in sentences:
            digest = hashlib.sha256(s.encode("utf-8")).digest()
            vec = [
                float(digest[i % len(digest)]) - 128.0
                for i in range(self.dim)
            ]
            if normalize_embeddings:
                norm = math.sqrt(sum(v * v for v in vec)) or 1.0
                vec = [v / norm for v in vec]
            out.append(vec)
        return out


def _fake_embedder(dim: int = 32) -> Embedder:
    enc = _FakeEncoder(dim=dim)
    return Embedder(model="fake", dim=dim, encoder=enc)


# ---------------------------------------------------------------------------
# Build a fresh graph DB for each test
# ---------------------------------------------------------------------------


@pytest.fixture
def repo_with_graph(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    shutil.copytree(FIXTURES / "python_sample", repo / "pkg")
    data_dir = repo / ".codegraph"
    data_dir.mkdir()
    store = SQLiteGraphStore(data_dir / "graph.db")
    GraphBuilder(repo, store).build(incremental=False)
    store.close()
    return repo


# ---------------------------------------------------------------------------
# 1-3 chunker tests
# ---------------------------------------------------------------------------


def test_chunk_repo_emits_one_per_callable_or_class(repo_with_graph: Path) -> None:
    chunks = list(chunk_repo(repo_with_graph))
    kinds = {c.kind for c in chunks}
    assert kinds.issubset({"FUNCTION", "METHOD", "CLASS"})
    qualnames = {c.qualname for c in chunks}
    # python_sample includes Animal, Dog, Cat, plus methods
    assert any("Animal" in qn for qn in qualnames)
    assert any("Dog" in qn for qn in qualnames)


def test_chunks_carry_metadata_when_present(repo_with_graph: Path) -> None:
    chunks = list(chunk_repo(repo_with_graph))
    # At least one chunk should expose params (a method with arguments).
    methods_with_params = [c for c in chunks if c.params]
    assert methods_with_params, "expected at least one chunk with params metadata"
    for chunk in methods_with_params:
        assert isinstance(chunk.params, list)
        assert all(isinstance(p, str) for p in chunk.params)


def test_chunk_repo_skips_module_and_test_kinds(repo_with_graph: Path) -> None:
    chunks = list(chunk_repo(repo_with_graph))
    kinds = {c.kind for c in chunks}
    for forbidden in {"MODULE", "FILE", "TEST", "IMPORT", "VARIABLE", "PARAMETER"}:
        assert forbidden not in kinds


# ---------------------------------------------------------------------------
# 4-5 embedder tests
# ---------------------------------------------------------------------------


def test_embedder_returns_correct_dim() -> None:
    emb = _fake_embedder(dim=64)
    vecs = emb.embed(["hello world"])
    assert len(vecs) == 1
    assert len(vecs[0]) == 64
    assert all(isinstance(v, float) for v in vecs[0])


def test_embedder_caches_encoder() -> None:
    enc = _FakeEncoder(dim=16)
    emb = Embedder(model="fake", dim=16, encoder=enc)
    emb.embed(["a"])
    emb.embed(["b"])
    # Second call must reuse the same encoder instance — no re-load.
    assert enc.calls == 2  # once per .embed call, but only one encoder build
    assert emb._encoder is enc


# ---------------------------------------------------------------------------
# 6 store roundtrip
# ---------------------------------------------------------------------------


def test_store_upsert_and_query_roundtrip(tmp_path: Path) -> None:
    store = EmbeddingStore(tmp_path / ".codegraph", dim=4, backend="json")
    rows = [
        StoredChunk(
            id="a",
            qualname="pkg.a",
            file="a.py",
            line_start=1,
            line_end=2,
            kind="FUNCTION",
            role=None,
            text="def a(): pass",
            vector=[1.0, 0.0, 0.0, 0.0],
        ),
        StoredChunk(
            id="b",
            qualname="pkg.b",
            file="b.py",
            line_start=1,
            line_end=2,
            kind="FUNCTION",
            role="HANDLER",
            text="def b(): pass",
            vector=[0.0, 1.0, 0.0, 0.0],
        ),
    ]
    store.upsert(rows)
    out = store.all()
    assert len(out) == 2
    hits = store.query([1.0, 0.0, 0.0, 0.0], k=2)
    assert hits[0][0].id == "a"
    assert hits[0][1] > hits[1][1]


# ---------------------------------------------------------------------------
# 7-9 query semantics
# ---------------------------------------------------------------------------


def test_semantic_query_sorted_descending(tmp_path: Path, repo_with_graph: Path) -> None:
    emb = _fake_embedder()
    build_index(
        repo_with_graph,
        embedder=emb,
        embeddings_dir=tmp_path,
        backend="json",
        force=True,
    )
    store = EmbeddingStore(tmp_path, backend="json")
    hits = semantic_query("dog speaks", k=5, embedder=emb, store=store)
    assert len(hits) > 0
    scores = [h.score for h in hits]
    assert scores == sorted(scores, reverse=True)


def test_hybrid_query_reranks_by_graph_distance(
    tmp_path: Path, repo_with_graph: Path
) -> None:
    emb = _fake_embedder()
    build_index(
        repo_with_graph,
        embedder=emb,
        embeddings_dir=tmp_path,
        backend="json",
        force=True,
    )
    store = EmbeddingStore(tmp_path, backend="json")
    sqlite_store = SQLiteGraphStore(repo_with_graph / ".codegraph" / "graph.db")
    graph = to_digraph(sqlite_store)
    sqlite_store.close()

    # Pick any qualname from the graph as focus
    focus = None
    for _, attrs in graph.nodes(data=True):
        qn = attrs.get("qualname")
        if qn and "." in str(qn):
            focus = str(qn)
            break
    assert focus is not None

    hits_pure = semantic_query("speak", k=5, embedder=emb, store=store)
    hits_hybrid = hybrid_query(
        "speak",
        k=5,
        focus_qn=focus,
        embedder=emb,
        store=store,
        graph=graph,
    )
    # Hybrid scores must reflect the 0.6/0.4 blend (so they differ from semantic).
    pure_scores = {h.qualname: h.score for h in hits_pure}
    differs = any(
        abs(h.score - pure_scores.get(h.qualname, h.score)) > 1e-9
        for h in hits_hybrid
    )
    assert differs


def test_hybrid_query_filters_by_role(tmp_path: Path) -> None:
    emb = _fake_embedder()
    rows = [
        StoredChunk(
            id="h1", qualname="api.handler_one", file="a.py",
            line_start=1, line_end=2, kind="FUNCTION", role="HANDLER",
            text="handler one", vector=emb.embed(["handler one"])[0],
        ),
        StoredChunk(
            id="s1", qualname="svc.service_one", file="b.py",
            line_start=1, line_end=2, kind="FUNCTION", role="SERVICE",
            text="service one", vector=emb.embed(["service one"])[0],
        ),
    ]
    store = EmbeddingStore(tmp_path, dim=32, backend="json")
    store.upsert(rows)
    hits = hybrid_query(
        "any text",
        k=5,
        role="HANDLER",
        embedder=emb,
        store=store,
        graph=None,
    )
    assert all(h.role == "HANDLER" for h in hits)
    assert any(h.qualname == "api.handler_one" for h in hits)


# ---------------------------------------------------------------------------
# 10-11 CLI error paths
# ---------------------------------------------------------------------------


def test_cli_embed_missing_graph(tmp_path: Path) -> None:
    runner = CliRunner()
    import os

    orig = os.getcwd()
    os.chdir(tmp_path)
    try:
        result = runner.invoke(app, ["embed"])
    finally:
        os.chdir(orig)
    assert result.exit_code == 1
    assert "codegraph build" in result.stdout


def test_cli_embed_missing_dependency(
    repo_with_graph: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner = CliRunner()
    from codegraph.embed import embedder as embedder_mod

    def _raise(_model: str) -> Any:
        raise embedder_mod.MissingDependencyError(
            "sentence-transformers is not installed."
        )

    monkeypatch.setattr(embedder_mod, "_load_sentence_transformer", _raise)

    import os

    orig = os.getcwd()
    os.chdir(repo_with_graph)
    try:
        result = runner.invoke(app, ["embed"])
    finally:
        os.chdir(orig)
    assert result.exit_code == 1
    assert "sentence-transformers" in result.stdout


# ---------------------------------------------------------------------------
# 12 MCP tool shape
# ---------------------------------------------------------------------------


def test_mcp_semantic_search_shape(
    tmp_path: Path, repo_with_graph: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    emb = _fake_embedder()
    data_dir = repo_with_graph / ".codegraph"
    build_index(
        repo_with_graph,
        embedder=emb,
        embeddings_dir=data_dir,
        backend="json",
        force=True,
    )

    # Patch Embedder() default constructor to use the fake encoder so the
    # MCP path doesn't try to download the real model.
    from codegraph.embed import embedder as embedder_mod

    monkeypatch.setattr(
        embedder_mod,
        "_load_sentence_transformer",
        lambda model: _FakeEncoder(dim=32),
    )

    import codegraph.mcp_server.server as mcp_server

    graph = nx.MultiDiGraph()
    result = mcp_server.tool_semantic_search(
        graph, query="dog", k=3, repo_root=repo_with_graph
    )

    assert isinstance(result, list)
    assert len(result) > 0
    first = result[0]
    for key in ("qualname", "file", "line", "kind", "score", "text_snippet"):
        assert key in first


def test_mcp_semantic_search_missing_index(tmp_path: Path) -> None:
    """If no index exists, the tool returns an error dict."""
    import os

    from codegraph.mcp_server.server import tool_semantic_search

    orig = os.getcwd()
    os.chdir(tmp_path)
    try:
        graph = nx.MultiDiGraph()
        result = tool_semantic_search(graph, query="dog", k=3)
    finally:
        os.chdir(orig)
    assert isinstance(result, dict)
    assert "error" in result


def test_mcp_tool_registry_includes_new_tools() -> None:
    from codegraph.mcp_server.server import tool_registry

    assert "semantic_search" in tool_registry
    assert "hybrid_search" in tool_registry


def test_index_missing_error_raised(tmp_path: Path) -> None:
    with pytest.raises(IndexMissingError):
        semantic_query("hello", k=3, repo_root=tmp_path)


def test_default_dim_constant_is_768() -> None:
    assert DEFAULT_DIM == 768


def test_chunk_id_is_stable() -> None:
    chunk = Chunk(
        qualname="a.b",
        file="a.py",
        line_start=1,
        line_end=2,
        kind="FUNCTION",
        text="def b(): pass",
    )
    assert chunk.id == "a.py::a.b::1"


def test_node_kinds_for_default_chunker_is_callable_set() -> None:
    """Sanity-check the default kinds match expectations."""
    from codegraph.embed.chunker import _DEFAULT_KINDS

    assert frozenset(
        {NodeKind.FUNCTION, NodeKind.METHOD, NodeKind.CLASS}
    ) == _DEFAULT_KINDS
