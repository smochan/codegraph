"""Local, open-weight embedding layer for codegraph (v0.3).

Public surface:

* :class:`Chunk` — a single embeddable code unit (function/method/class).
* :class:`Hit` — a search result.
* :func:`chunk_repo` — turn graph nodes into chunks.
* :func:`build_index` — chunk + embed + write index to ``.codegraph/embeddings.lance``.
* :func:`query` — convenience wrapper around :func:`semantic_query`.

The heavy dependencies (``sentence-transformers``, ``lancedb``) are imported
lazily.  Install with ``pip install -e ".[embed]"``.
"""
from __future__ import annotations

from codegraph.embed.chunker import Chunk, chunk_repo
from codegraph.embed.query import Hit, hybrid_query, semantic_query
from codegraph.embed.store import EmbeddingStore, build_index

__all__ = [
    "Chunk",
    "EmbeddingStore",
    "Hit",
    "build_index",
    "chunk_repo",
    "hybrid_query",
    "query",
    "semantic_query",
]


def query(text: str, *, k: int = 5) -> list[Hit]:
    """Shortcut: run a semantic query against the cwd ``.codegraph`` index."""
    return semantic_query(text, k=k)
