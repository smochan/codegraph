"""Tests for TypeScript extractor."""
from __future__ import annotations

from pathlib import Path

import pytest

from codegraph.graph.schema import EdgeKind, NodeKind
from codegraph.parsers.typescript import TypeScriptExtractor

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "ts_sample"


@pytest.fixture
def extractor() -> TypeScriptExtractor:
    return TypeScriptExtractor()


def test_parse_utils_functions(extractor: TypeScriptExtractor) -> None:
    nodes, _ = extractor.parse_file(FIXTURE_DIR / "utils.ts", FIXTURE_DIR)
    names = {n.name for n in nodes}
    kinds = {n.kind for n in nodes}
    assert NodeKind.MODULE in kinds
    assert NodeKind.FUNCTION in kinds
    assert "add" in names
    assert "formatName" in names
    assert "multiply" in names


def test_parse_component_class(extractor: TypeScriptExtractor) -> None:
    nodes, _ = extractor.parse_file(FIXTURE_DIR / "Component.tsx", FIXTURE_DIR)
    names = {n.name for n in nodes}
    kinds = {n.kind for n in nodes}
    assert NodeKind.CLASS in kinds
    assert "Greeter" in names


def test_parse_component_method(extractor: TypeScriptExtractor) -> None:
    nodes, _ = extractor.parse_file(FIXTURE_DIR / "Component.tsx", FIXTURE_DIR)
    methods = [n for n in nodes if n.kind == NodeKind.METHOD]
    assert len(methods) >= 1


def test_parse_component_inherits(extractor: TypeScriptExtractor) -> None:
    _, edges = extractor.parse_file(FIXTURE_DIR / "Component.tsx", FIXTURE_DIR)
    inherits = [e for e in edges if e.kind == EdgeKind.INHERITS]
    assert len(inherits) >= 1


def test_parse_component_imports(extractor: TypeScriptExtractor) -> None:
    _, edges = extractor.parse_file(FIXTURE_DIR / "Component.tsx", FIXTURE_DIR)
    imports = [e for e in edges if e.kind == EdgeKind.IMPORTS]
    assert len(imports) >= 1
    sources = [e.metadata.get("source") for e in imports]
    assert "react" in sources


def test_parse_test_file_marks_test(extractor: TypeScriptExtractor) -> None:
    nodes, _ = extractor.parse_file(
        FIXTURE_DIR / "Component.test.tsx", FIXTURE_DIR
    )
    module_nodes = [n for n in nodes if n.kind == NodeKind.MODULE]
    assert len(module_nodes) >= 1
    assert module_nodes[0].metadata.get("is_test") is True


def test_parse_component_calls(extractor: TypeScriptExtractor) -> None:
    _, edges = extractor.parse_file(FIXTURE_DIR / "Component.tsx", FIXTURE_DIR)
    calls = [e for e in edges if e.kind == EdgeKind.CALLS]
    assert len(calls) >= 1


def test_parse_arrow_function(extractor: TypeScriptExtractor) -> None:
    nodes, _ = extractor.parse_file(FIXTURE_DIR / "utils.ts", FIXTURE_DIR)
    names = {n.name for n in nodes if n.kind == NodeKind.FUNCTION}
    assert "multiply" in names
