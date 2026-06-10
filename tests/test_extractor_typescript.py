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


def test_parse_named_imports_emit_per_name_edges(
    extractor: TypeScriptExtractor,
) -> None:
    """`import { formatName } from './utils'` should emit a per-name IMPORTS
    edge with imported_name='formatName' and target_name './utils.formatName'.
    """
    _, edges = extractor.parse_file(FIXTURE_DIR / "Component.tsx", FIXTURE_DIR)
    imports = [e for e in edges if e.kind == EdgeKind.IMPORTS]
    named = [
        e for e in imports
        if e.metadata.get("imported_name") == "formatName"
    ]
    assert named, (
        f"expected per-name IMPORTS edge for formatName, got {imports}"
    )
    target = named[0].metadata.get("target_name")
    assert target is not None and target.endswith(".formatName"), target


def test_parse_arrow_function(extractor: TypeScriptExtractor) -> None:
    nodes, _ = extractor.parse_file(FIXTURE_DIR / "utils.ts", FIXTURE_DIR)
    names = {n.name for n in nodes if n.kind == NodeKind.FUNCTION}
    assert "multiply" in names


# --- exported + any metadata -----------------------------------------------

LINT_SAMPLE_DIR = Path(__file__).parent / "fixtures" / "lint_sample" / "src"


def test_exported_flag_set_on_exported_function(
    extractor: TypeScriptExtractor,
) -> None:
    nodes, _ = extractor.parse_file(LINT_SAMPLE_DIR / "api.ts", LINT_SAMPLE_DIR)
    funcs = {n.name: n for n in nodes if n.kind == NodeKind.FUNCTION}
    assert funcs["processPayload"].metadata.get("exported") is True
    assert funcs["typedHandler"].metadata.get("exported") is True
    assert funcs["handleInput"].metadata.get("exported") is True


def test_exported_flag_absent_on_non_exported_function(
    extractor: TypeScriptExtractor,
) -> None:
    nodes, _ = extractor.parse_file(LINT_SAMPLE_DIR / "api.ts", LINT_SAMPLE_DIR)
    funcs = {n.name: n for n in nodes if n.kind == NodeKind.FUNCTION}
    assert not funcs["internalProcess"].metadata.get("exported")


def test_any_params_recorded_for_any_param_function(
    extractor: TypeScriptExtractor,
) -> None:
    nodes, _ = extractor.parse_file(LINT_SAMPLE_DIR / "api.ts", LINT_SAMPLE_DIR)
    funcs = {n.name: n for n in nodes if n.kind == NodeKind.FUNCTION}
    assert funcs["processPayload"].metadata.get("any_params") == ["x"]
    assert funcs["handleInput"].metadata.get("any_params") == ["data"]


def test_any_params_absent_for_typed_function(
    extractor: TypeScriptExtractor,
) -> None:
    nodes, _ = extractor.parse_file(LINT_SAMPLE_DIR / "api.ts", LINT_SAMPLE_DIR)
    funcs = {n.name: n for n in nodes if n.kind == NodeKind.FUNCTION}
    assert not funcs["typedHandler"].metadata.get("any_params")


def test_any_return_set_when_return_type_is_any(
    extractor: TypeScriptExtractor,
) -> None:
    nodes, _ = extractor.parse_file(LINT_SAMPLE_DIR / "api.ts", LINT_SAMPLE_DIR)
    funcs = {n.name: n for n in nodes if n.kind == NodeKind.FUNCTION}
    assert funcs["processPayload"].metadata.get("any_return") is True


def test_any_return_absent_for_typed_return(
    extractor: TypeScriptExtractor,
) -> None:
    nodes, _ = extractor.parse_file(LINT_SAMPLE_DIR / "api.ts", LINT_SAMPLE_DIR)
    funcs = {n.name: n for n in nodes if n.kind == NodeKind.FUNCTION}
    assert not funcs["typedHandler"].metadata.get("any_return")
    # arrow with any param but typed return should NOT set any_return
    assert not funcs["handleInput"].metadata.get("any_return")
