"""Tests for Python extractor."""
from __future__ import annotations

from pathlib import Path

import pytest

from codegraph.graph.schema import EdgeKind, NodeKind
from codegraph.parsers.python import PythonExtractor

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "python_sample"


@pytest.fixture
def extractor() -> PythonExtractor:
    return PythonExtractor()


def test_parse_models(extractor: PythonExtractor) -> None:
    nodes, _ = extractor.parse_file(FIXTURE_DIR / "models.py", FIXTURE_DIR)
    kinds = {n.kind for n in nodes}
    names = {n.name for n in nodes}
    assert NodeKind.MODULE in kinds
    assert NodeKind.CLASS in kinds
    assert NodeKind.METHOD in kinds
    assert "Animal" in names
    assert "Dog" in names
    assert "Cat" in names


def test_parse_models_class_docstring(extractor: PythonExtractor) -> None:
    nodes, _ = extractor.parse_file(FIXTURE_DIR / "models.py", FIXTURE_DIR)
    animal = next(n for n in nodes if n.name == "Animal")
    assert animal.docstring is not None
    assert "animal" in animal.docstring.lower()


def test_parse_models_inherits_edge(extractor: PythonExtractor) -> None:
    _, edges = extractor.parse_file(FIXTURE_DIR / "models.py", FIXTURE_DIR)
    inherits = [e for e in edges if e.kind == EdgeKind.INHERITS]
    assert len(inherits) >= 1
    target_names = [e.metadata.get("target_name") for e in inherits]
    assert "Animal" in target_names


def test_parse_models_defined_in_edges(extractor: PythonExtractor) -> None:
    _, edges = extractor.parse_file(FIXTURE_DIR / "models.py", FIXTURE_DIR)
    defined_in = [e for e in edges if e.kind == EdgeKind.DEFINED_IN]
    assert len(defined_in) >= 3


def test_parse_utils_imports(extractor: PythonExtractor) -> None:
    _, edges = extractor.parse_file(FIXTURE_DIR / "utils.py", FIXTURE_DIR)
    imports = [e for e in edges if e.kind == EdgeKind.IMPORTS]
    target_names = [str(e.metadata.get("target_name")) for e in imports]
    assert any(
        "os" in n or "pathlib" in n or "models" in n for n in target_names
    )


def test_parse_utils_calls(extractor: PythonExtractor) -> None:
    _, edges = extractor.parse_file(FIXTURE_DIR / "utils.py", FIXTURE_DIR)
    calls = [e for e in edges if e.kind == EdgeKind.CALLS]
    assert len(calls) >= 1


def test_parse_test_file_marks_test(extractor: PythonExtractor) -> None:
    nodes, _ = extractor.parse_file(
        FIXTURE_DIR / "test_models.py", FIXTURE_DIR
    )
    module_nodes = [n for n in nodes if n.kind == NodeKind.MODULE]
    assert len(module_nodes) >= 1
    assert module_nodes[0].metadata.get("is_test") is True
    test_nodes = [n for n in nodes if n.kind == NodeKind.TEST]
    assert len(test_nodes) >= 1
