"""Direct unit tests for codegraph.embed.store._JsonBackend and embedder.

The Embedder.embed method is the public encoding entry point — exercise it
with a deterministic in-memory fake encoder.
"""
from __future__ import annotations

import hashlib
import math
from pathlib import Path
from typing import Any

from codegraph.embed.embedder import Embedder
from codegraph.embed.store import StoredChunk, _JsonBackend

# ---------------------------------------------------------------------------
# JsonBackend tests
# ---------------------------------------------------------------------------

def _row(rid: str, vec: list[float] | None = None) -> StoredChunk:
    return StoredChunk(
        id=rid,
        qualname=f"pkg.{rid}",
        file=f"{rid}.py",
        line_start=1,
        line_end=5,
        kind="FUNCTION",
        role=None,
        text=f"def {rid}(): pass",
        vector=vec or [1.0, 0.0],
    )


def test_json_backend_upsert_and_all(tmp_path: Path) -> None:
    backend = _JsonBackend(tmp_path / "x.json")
    backend.upsert([_row("a"), _row("b")])
    out = backend.all()
    assert {r.id for r in out} == {"a", "b"}


def test_json_backend_upsert_replaces_existing_id(tmp_path: Path) -> None:
    backend = _JsonBackend(tmp_path / "x.json")
    backend.upsert([_row("a", [1.0, 0.0])])
    backend.upsert([_row("a", [0.0, 1.0])])
    rows = backend.all()
    assert len(rows) == 1
    assert rows[0].vector == [0.0, 1.0]


def test_json_backend_replace_all_clears_old(tmp_path: Path) -> None:
    backend = _JsonBackend(tmp_path / "x.json")
    backend.upsert([_row("a"), _row("b")])
    backend.replace_all([_row("c")])
    ids = {r.id for r in backend.all()}
    assert ids == {"c"}


def test_json_backend_query_returns_top_k_sorted(tmp_path: Path) -> None:
    backend = _JsonBackend(tmp_path / "x.json")
    backend.upsert(
        [
            _row("a", [1.0, 0.0]),
            _row("b", [0.0, 1.0]),
            _row("c", [0.7, 0.7]),
        ]
    )
    hits = backend.query([1.0, 0.0], k=3)
    assert hits[0][0].id == "a"
    # scores are descending
    scores = [s for _, s in hits]
    assert scores == sorted(scores, reverse=True)


def test_json_backend_query_respects_k_limit(tmp_path: Path) -> None:
    backend = _JsonBackend(tmp_path / "x.json")
    backend.upsert([_row("a"), _row("b"), _row("c")])
    hits = backend.query([1.0, 0.0], k=2)
    assert len(hits) == 2


def test_json_backend_size_bytes_zero_when_missing(tmp_path: Path) -> None:
    backend = _JsonBackend(tmp_path / "missing.json")
    # File not yet flushed because no upsert
    assert backend.size_bytes() == 0


def test_json_backend_size_bytes_after_write(tmp_path: Path) -> None:
    backend = _JsonBackend(tmp_path / "x.json")
    backend.upsert([_row("a")])
    assert backend.size_bytes() > 0


def test_json_backend_persists_across_instances(tmp_path: Path) -> None:
    path = tmp_path / "x.json"
    backend1 = _JsonBackend(path)
    backend1.upsert([_row("a")])
    backend2 = _JsonBackend(path)
    assert {r.id for r in backend2.all()} == {"a"}


def test_json_backend_recovers_from_corrupt_file(tmp_path: Path) -> None:
    path = tmp_path / "x.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("not-json{{", encoding="utf-8")
    backend = _JsonBackend(path)
    assert backend.all() == []


# ---------------------------------------------------------------------------
# Embedder.embed tests with fake encoder
# ---------------------------------------------------------------------------


class _FakeEncoder:
    def __init__(self, dim: int = 8) -> None:
        self.dim = dim
        self.calls = 0

    def encode(self, sentences: list[str], **kwargs: Any) -> list[list[float]]:
        self.calls += 1
        out: list[list[float]] = []
        for s in sentences:
            digest = hashlib.sha256(s.encode("utf-8")).digest()
            vec = [float(digest[i % len(digest)]) for i in range(self.dim)]
            norm = math.sqrt(sum(v * v for v in vec)) or 1.0
            vec = [v / norm for v in vec]
            out.append(vec)
        return out


def test_embedder_embed_empty_list_returns_empty() -> None:
    enc = _FakeEncoder()
    emb = Embedder(model="fake", dim=8, encoder=enc)
    assert emb.embed([]) == []
    assert enc.calls == 0


def test_embedder_embed_one_text() -> None:
    enc = _FakeEncoder(dim=8)
    emb = Embedder(model="fake", dim=8, encoder=enc)
    out = emb.embed(["hello"])
    assert len(out) == 1
    assert len(out[0]) == 8


def test_embedder_embed_multiple_texts() -> None:
    enc = _FakeEncoder(dim=8)
    emb = Embedder(model="fake", dim=8, encoder=enc)
    out = emb.embed(["a", "b", "c"])
    assert len(out) == 3
    assert all(len(v) == 8 for v in out)


def test_embedder_embed_returns_floats() -> None:
    enc = _FakeEncoder(dim=4)
    emb = Embedder(model="fake", dim=4, encoder=enc)
    out = emb.embed(["x"])
    assert all(isinstance(v, float) for v in out[0])


def test_embedder_dim_property_uses_provided_value() -> None:
    enc = _FakeEncoder(dim=8)
    emb = Embedder(model="fake", dim=16, encoder=enc)
    # When dim is explicitly set, it shouldn't trigger encoding.
    assert emb.dim == 16
    assert enc.calls == 0
