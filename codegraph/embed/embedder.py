"""Sentence-transformers wrapper.

The model is lazy-loaded so unit tests can substitute a deterministic fake
without pulling the real dependency tree.
"""
from __future__ import annotations

import os
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Protocol

DEFAULT_MODEL = "nomic-ai/CodeRankEmbed"
DEFAULT_DIM = 768


class _EncoderLike(Protocol):
    def encode(
        self,
        sentences: Sequence[str],
        *,
        batch_size: int = ...,
        show_progress_bar: bool = ...,
        convert_to_numpy: bool = ...,
        normalize_embeddings: bool = ...,
    ) -> Any:
        ...


def _cache_dir() -> Path:
    """Where downloaded models live.  Honours ``XDG_CACHE_HOME`` if set."""
    xdg = os.environ.get("XDG_CACHE_HOME")
    base = Path(xdg) if xdg else Path.home() / ".cache"
    return base / "codegraph" / "models"


class MissingDependencyError(RuntimeError):
    """Raised when the optional ``embed`` extra is not installed."""


def _load_sentence_transformer(model: str) -> _EncoderLike:
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError as exc:  # pragma: no cover — exercised via mock test
        raise MissingDependencyError(
            "sentence-transformers is not installed.\n"
            "Run: pip install -e \".[embed]\""
        ) from exc

    cache = _cache_dir()
    cache.mkdir(parents=True, exist_ok=True)
    encoder: _EncoderLike = SentenceTransformer(
        model, cache_folder=str(cache), trust_remote_code=True
    )
    return encoder


class Embedder:
    """Tiny wrapper around a sentence-transformer model.

    The actual encoder is loaded lazily on first :meth:`embed` call so that:

    * Construction is cheap and side-effect free (good for tests).
    * Multiple embedders can co-exist without re-downloading.

    Pass ``encoder`` to inject a fake / mock for tests.
    """

    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        *,
        dim: int | None = None,
        encoder: _EncoderLike | None = None,
    ) -> None:
        self.model = model
        self._encoder: _EncoderLike | None = encoder
        self._dim: int | None = dim

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    def _ensure_loaded(self) -> _EncoderLike:
        if self._encoder is None:
            self._encoder = _load_sentence_transformer(self.model)
        return self._encoder

    @property
    def dim(self) -> int:
        if self._dim is not None:
            return self._dim
        # Probe the encoder with a single token so we don't have to assume.
        vecs = self.embed(["probe"])
        self._dim = len(vecs[0])
        return self._dim

    # ------------------------------------------------------------------
    # Encoding
    # ------------------------------------------------------------------
    def embed(self, texts: Sequence[str], *, batch_size: int = 32) -> list[list[float]]:
        """Return one row of floats per input string."""
        if not texts:
            return []
        enc = self._ensure_loaded()
        out = enc.encode(
            list(texts),
            batch_size=batch_size,
            show_progress_bar=False,
            convert_to_numpy=True,
            normalize_embeddings=True,
        )
        # Accept numpy arrays, lists, or anything that iterates rows.
        return [list(map(float, row)) for row in out]
