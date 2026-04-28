"""Query helpers for the embeddings index."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from codegraph.embed.embedder import Embedder
from codegraph.embed.store import EmbeddingStore, StoredChunk


@dataclass(frozen=True)
class Hit:
    """A single search result."""

    qualname: str
    file: str
    line: int
    kind: str
    role: str | None
    score: float
    text_snippet: str

    # pragma: codegraph-public-api
    def as_dict(self, *, score_field: str = "score") -> dict[str, Any]:
        return {
            "qualname": self.qualname,
            "file": self.file,
            "line": self.line,
            "kind": self.kind,
            "role": self.role,
            score_field: round(float(self.score), 6),
            "text_snippet": self.text_snippet,
        }


def _snippet(text: str, max_lines: int = 6, max_chars: int = 400) -> str:
    lines = text.splitlines()[:max_lines]
    snippet = "\n".join(lines)
    if len(snippet) > max_chars:
        snippet = snippet[:max_chars] + "…"
    return snippet


def _index_dir(repo_root: Path | None = None) -> Path:
    return (repo_root or Path.cwd()) / ".codegraph"


class IndexMissingError(RuntimeError):
    """Raised when the embeddings index does not exist on disk."""


def _open_store(repo_root: Path | None = None) -> EmbeddingStore:
    base = _index_dir(repo_root)
    lance = base / "embeddings.lance"
    json_fb = base / "embeddings.json"
    if not lance.exists() and not json_fb.exists():
        raise IndexMissingError(
            "no embedding index — run `codegraph embed` first"
        )
    backend = "auto" if lance.exists() else "json"
    return EmbeddingStore(base, backend=backend)


def _to_hit(row: StoredChunk, score: float) -> Hit:
    return Hit(
        qualname=row.qualname,
        file=row.file,
        line=row.line_start,
        kind=row.kind,
        role=row.role,
        score=score,
        text_snippet=_snippet(row.text),
    )


def semantic_query(
    text: str,
    *,
    k: int = 5,
    repo_root: Path | None = None,
    embedder: Embedder | None = None,
    store: EmbeddingStore | None = None,
) -> list[Hit]:
    """Pure cosine-similarity ranking against the index."""
    s = store or _open_store(repo_root)
    emb = embedder or Embedder()
    vector = emb.embed([text])[0]
    hits = s.query(vector, k=k)
    return [_to_hit(row, score) for row, score in hits]


def hybrid_query(
    text: str,
    *,
    k: int = 5,
    role: str | None = None,
    focus_qn: str | None = None,
    repo_root: Path | None = None,
    embedder: Embedder | None = None,
    store: EmbeddingStore | None = None,
    graph: Any | None = None,
) -> list[Hit]:
    """Blend semantic similarity with graph distance from a focus node.

    ``final_score = 0.6 * cosine + 0.4 * (1 / (1 + graph_hops))``
    """
    s = store or _open_store(repo_root)
    emb = embedder or Embedder()
    vector = emb.embed([text])[0]

    pool_size = max(k * 4, 20)
    raw = s.query(vector, k=pool_size)

    if role is not None:
        raw = [(row, score) for row, score in raw if row.role == role]

    if focus_qn is None:
        return [_to_hit(row, score) for row, score in raw[:k]]

    g = graph if graph is not None else _load_graph(repo_root)
    focus_id = _find_node_by_qualname(g, focus_qn) if g is not None else None

    rescored: list[tuple[StoredChunk, float, float]] = []
    for row, semantic in raw:
        target_id = _find_node_by_qualname(g, row.qualname) if g is not None else None
        hops = _graph_distance(g, focus_id, target_id) if g is not None else None
        graph_score = 0.0 if hops is None else 1.0 / (1.0 + float(hops))
        final = 0.6 * float(semantic) + 0.4 * graph_score
        rescored.append((row, final, semantic))

    rescored.sort(key=lambda triple: triple[1], reverse=True)
    return [_to_hit(row, final) for row, final, _ in rescored[:k]]


# ---------------------------------------------------------------------------
# Graph helpers (lazy nx import; tolerate missing graph)
# ---------------------------------------------------------------------------


def _load_graph(repo_root: Path | None) -> Any | None:
    try:
        from codegraph.graph.store_networkx import to_digraph
        from codegraph.graph.store_sqlite import SQLiteGraphStore
    except Exception:  # pragma: no cover
        return None

    db = (repo_root or Path.cwd()) / ".codegraph" / "graph.db"
    if not db.exists():
        return None
    store = SQLiteGraphStore(db)
    try:
        return to_digraph(store)
    finally:
        store.close()


def _find_node_by_qualname(graph: Any, qualname: str) -> str | None:
    if graph is None:
        return None
    if qualname in graph:
        return qualname
    q = qualname.lower()
    for nid, attrs in graph.nodes(data=True):
        if str(attrs.get("qualname") or "").lower() == q:
            return str(nid)
    return None


def _graph_distance(graph: Any, src: str | None, dst: str | None) -> int | None:
    if graph is None or src is None or dst is None:
        return None
    if src == dst:
        return 0
    try:
        import networkx as nx

        ug = graph.to_undirected(as_view=True) if hasattr(graph, "to_undirected") else graph
        return int(nx.shortest_path_length(ug, src, dst))
    except Exception:
        return None
