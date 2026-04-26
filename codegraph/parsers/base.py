"""Base classes and helpers for tree-sitter-based extractors."""
from __future__ import annotations

import abc
from functools import lru_cache
from pathlib import Path

import tree_sitter

from codegraph.graph.schema import Edge, Node

_EXTRACTOR_REGISTRY: dict[str, ExtractorBase] = {}


class ExtractorBase(abc.ABC):
    language: str
    extensions: tuple[str, ...]

    @abc.abstractmethod
    def parse_file(
        self, path: Path, repo_root: Path
    ) -> tuple[list[Node], list[Edge]]:
        """Parse a file and return (nodes, edges)."""


@lru_cache(maxsize=16)
def load_parser(language: str) -> tree_sitter.Parser:
    """Return a cached tree_sitter.Parser for the given language key."""
    lang = _get_language(language)
    return tree_sitter.Parser(lang)


@lru_cache(maxsize=16)
def _get_language(language: str) -> tree_sitter.Language:
    if language == "python":
        import tree_sitter_python
        return tree_sitter.Language(tree_sitter_python.language())
    elif language == "typescript":
        import tree_sitter_typescript
        return tree_sitter.Language(tree_sitter_typescript.language_typescript())
    elif language == "tsx":
        import tree_sitter_typescript
        return tree_sitter.Language(tree_sitter_typescript.language_tsx())
    elif language in ("javascript", "jsx"):
        import tree_sitter_javascript
        return tree_sitter.Language(tree_sitter_javascript.language())
    else:
        raise ValueError(f"Unsupported language: {language}")


def node_text(ts_node: tree_sitter.Node, source_bytes: bytes) -> str:
    return source_bytes[ts_node.start_byte:ts_node.end_byte].decode(
        "utf-8", errors="replace"
    )


def register_extractor(cls: type[ExtractorBase]) -> type[ExtractorBase]:
    """Class decorator to register an extractor by its extensions."""
    instance = cls()
    for ext in cls.extensions:
        _EXTRACTOR_REGISTRY[ext] = instance
    return cls


def get_extractor_for(path: Path) -> ExtractorBase | None:
    """Return the extractor for the given file extension, or None."""
    return _EXTRACTOR_REGISTRY.get(path.suffix.lower())
