"""On-disk vector store.

Tries LanceDB first (the production backend) and falls back to a tiny JSON
file when the optional ``embed`` extra isn't installed.  The fallback is good
enough for unit tests and for repos that just want a quick local index without
pulling the full Arrow / LanceDB stack.
"""
from __future__ import annotations

import contextlib
import json
import math
from collections.abc import Iterable, Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from codegraph.embed.chunker import Chunk  # noqa: F401  (re-export friendly)
from codegraph.embed.embedder import DEFAULT_DIM, DEFAULT_MODEL, Embedder

_STORE_FILENAME = "embeddings.lance"
_FALLBACK_FILENAME = "embeddings.json"


@dataclass
class StoredChunk:
    id: str
    qualname: str
    file: str
    line_start: int
    line_end: int
    kind: str
    role: str | None
    text: str
    vector: list[float] = field(default_factory=list)

    # pragma: codegraph-public-api
    def to_json(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "qualname": self.qualname,
            "file": self.file,
            "line_start": self.line_start,
            "line_end": self.line_end,
            "kind": self.kind,
            "role": self.role,
            "text": self.text,
            "vector": list(self.vector),
        }

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> StoredChunk:
        return cls(
            id=str(data["id"]),
            qualname=str(data["qualname"]),
            file=str(data["file"]),
            line_start=int(data["line_start"]),
            line_end=int(data["line_end"]),
            kind=str(data["kind"]),
            role=(str(data["role"]) if data.get("role") else None),
            text=str(data["text"]),
            vector=[float(v) for v in data.get("vector") or []],
        )


def _cosine(a: Sequence[float], b: Sequence[float]) -> float:
    if not a or not b:
        return 0.0
    dot = 0.0
    na = 0.0
    nb = 0.0
    for x, y in zip(a, b, strict=False):
        dot += x * y
        na += x * x
        nb += y * y
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (math.sqrt(na) * math.sqrt(nb))


# ---------------------------------------------------------------------------
# Backend abstraction
# ---------------------------------------------------------------------------

class _JsonBackend:
    """JSON-backed backend.  Used in tests and as the no-deps fallback."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._rows: list[StoredChunk] = []
        if self.path.exists():
            try:
                raw = json.loads(self.path.read_text(encoding="utf-8"))
                self._rows = [StoredChunk.from_json(r) for r in raw]
            except (OSError, json.JSONDecodeError, KeyError, TypeError):
                self._rows = []

    def upsert(self, rows: Iterable[StoredChunk]) -> None:
        new = list(rows)
        new_ids = {r.id for r in new}
        kept = [r for r in self._rows if r.id not in new_ids]
        self._rows = kept + new
        self._flush()

    def replace_all(self, rows: Iterable[StoredChunk]) -> None:
        self._rows = list(rows)
        self._flush()

    def _flush(self) -> None:
        payload = [r.to_json() for r in self._rows]
        self.path.write_text(json.dumps(payload), encoding="utf-8")

    def all(self) -> list[StoredChunk]:
        return list(self._rows)

    def query(self, vector: Sequence[float], k: int) -> list[tuple[StoredChunk, float]]:
        scored = [(row, _cosine(vector, row.vector)) for row in self._rows]
        scored.sort(key=lambda pair: pair[1], reverse=True)
        return scored[:k]

    def size_bytes(self) -> int:
        return self.path.stat().st_size if self.path.exists() else 0


class _LanceBackend:
    """LanceDB backend.  Schema mirrors :class:`StoredChunk`."""

    def __init__(self, path: Path, dim: int) -> None:
        import lancedb
        import pyarrow as pa

        self.path = path
        self._dim = dim
        self._pa = pa
        self._db = lancedb.connect(str(path))
        self._schema = self._make_schema(dim)
        if "chunks" in self._db.table_names():
            self._table = self._db.open_table("chunks")
        else:
            self._table = self._db.create_table("chunks", schema=self._schema, mode="create")

    def _make_schema(self, dim: int) -> Any:
        pa = self._pa
        return pa.schema(
            [
                ("id", pa.string()),
                ("qualname", pa.string()),
                ("file", pa.string()),
                ("line_start", pa.int64()),
                ("line_end", pa.int64()),
                ("kind", pa.string()),
                ("role", pa.string()),
                ("text", pa.string()),
                ("vector", pa.list_(pa.float32(), dim)),
            ]
        )

    def _to_dict(self, row: StoredChunk) -> dict[str, Any]:
        return {
            "id": row.id,
            "qualname": row.qualname,
            "file": row.file,
            "line_start": row.line_start,
            "line_end": row.line_end,
            "kind": row.kind,
            "role": row.role or "",
            "text": row.text,
            "vector": row.vector,
        }

    def upsert(self, rows: Iterable[StoredChunk]) -> None:
        batch = [self._to_dict(r) for r in rows]
        if not batch:
            return
        ids = ", ".join(f"'{r['id']}'" for r in batch)
        with contextlib.suppress(Exception):
            self._table.delete(f"id IN ({ids})")
        self._table.add(batch)

    def replace_all(self, rows: Iterable[StoredChunk]) -> None:
        batch = [self._to_dict(r) for r in rows]
        with contextlib.suppress(Exception):
            self._db.drop_table("chunks", ignore_missing=True)
        self._table = self._db.create_table("chunks", schema=self._schema, mode="create")
        if batch:
            self._table.add(batch)

    def _row_from_record(self, r: dict[str, Any]) -> StoredChunk:
        return StoredChunk(
            id=str(r["id"]),
            qualname=str(r["qualname"]),
            file=str(r["file"]),
            line_start=int(r["line_start"]),
            line_end=int(r["line_end"]),
            kind=str(r["kind"]),
            role=str(r["role"]) or None,
            text=str(r["text"]),
            vector=list(r["vector"]),
        )

    def all(self) -> list[StoredChunk]:
        rows = self._table.to_pandas().to_dict(orient="records")
        return [self._row_from_record(r) for r in rows]

    def query(self, vector: Sequence[float], k: int) -> list[tuple[StoredChunk, float]]:
        results = self._table.search(list(vector)).limit(k).to_pandas()
        out: list[tuple[StoredChunk, float]] = []
        for r in results.to_dict(orient="records"):
            chunk = self._row_from_record(r)
            distance = float(r.get("_distance", 0.0))
            similarity = 1.0 / (1.0 + distance)
            out.append((chunk, similarity))
        return out

    def size_bytes(self) -> int:
        total = 0
        for p in self.path.rglob("*"):
            if p.is_file():
                total += p.stat().st_size
        return total


# ---------------------------------------------------------------------------
# Public store
# ---------------------------------------------------------------------------


class EmbeddingStore:
    """High-level interface that auto-selects a backend.

    ``backend='auto'`` (default) tries LanceDB and falls back to JSON.
    ``backend='json'`` forces the lightweight backend (used in tests).
    """

    def __init__(
        self,
        data_dir: Path,
        *,
        dim: int = DEFAULT_DIM,
        backend: str = "auto",
    ) -> None:
        self.data_dir = data_dir
        self.dim = dim
        self.backend_name: str
        self._backend: _LanceBackend | _JsonBackend
        data_dir.mkdir(parents=True, exist_ok=True)

        if backend == "json":
            self._backend = _JsonBackend(data_dir / _FALLBACK_FILENAME)
            self.backend_name = "json"
            return

        try:
            self._backend = _LanceBackend(data_dir / _STORE_FILENAME, dim=dim)
            self.backend_name = "lancedb"
        except ImportError:
            if backend == "lancedb":
                raise
            self._backend = _JsonBackend(data_dir / _FALLBACK_FILENAME)
            self.backend_name = "json"

    # ------------------------------------------------------------------
    # pragma: codegraph-public-api
    def upsert(self, rows: Iterable[StoredChunk]) -> None:
        self._backend.upsert(rows)

    # pragma: codegraph-public-api
    def replace_all(self, rows: Iterable[StoredChunk]) -> None:
        self._backend.replace_all(rows)

    # pragma: codegraph-public-api
    def all(self) -> list[StoredChunk]:
        return self._backend.all()

    # pragma: codegraph-public-api
    def query(self, vector: Sequence[float], k: int = 5) -> list[tuple[StoredChunk, float]]:
        return self._backend.query(vector, k)

    # pragma: codegraph-public-api
    def size_bytes(self) -> int:
        return self._backend.size_bytes()


# ---------------------------------------------------------------------------
# build_index — orchestrator wired up to chunker + embedder
# ---------------------------------------------------------------------------


@dataclass
class IndexStats:
    chunks_indexed: int
    model: str
    dim: int
    backend: str
    on_disk_bytes: int

    # pragma: codegraph-public-api
    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_index(
    repo_root: Path,
    *,
    db_path: Path | None = None,
    embeddings_dir: Path | None = None,
    embedder: Embedder | None = None,
    model: str = DEFAULT_MODEL,
    force: bool = False,
    progress: Any | None = None,
    backend: str = "auto",
) -> IndexStats:
    """Chunk + embed + persist.

    ``progress`` (optional) is anything with an ``advance(step: int)`` method
    — typically a ``rich.progress.Progress`` task.  Pass ``None`` to disable.
    """
    from codegraph.embed.chunker import chunk_repo

    chunks = list(chunk_repo(repo_root, db_path=db_path))
    emb = embedder or Embedder(model)

    rows: list[StoredChunk] = []
    dim = DEFAULT_DIM
    if chunks:
        vectors = emb.embed([c.text for c in chunks], batch_size=32)
        dim = len(vectors[0]) if vectors else DEFAULT_DIM
        for c, v in zip(chunks, vectors, strict=False):
            rows.append(
                StoredChunk(
                    id=c.id,
                    qualname=c.qualname,
                    file=c.file,
                    line_start=c.line_start,
                    line_end=c.line_end,
                    kind=c.kind,
                    role=c.role,
                    text=c.text,
                    vector=v,
                )
            )
            if progress is not None:
                with contextlib.suppress(Exception):
                    progress.advance(1)

    out_dir = embeddings_dir or (repo_root / ".codegraph")
    store = EmbeddingStore(out_dir, dim=dim, backend=backend)
    if force:
        store.replace_all(rows)
    else:
        store.upsert(rows)

    return IndexStats(
        chunks_indexed=len(rows),
        model=emb.model,
        dim=dim,
        backend=store.backend_name,
        on_disk_bytes=store.size_bytes(),
    )
