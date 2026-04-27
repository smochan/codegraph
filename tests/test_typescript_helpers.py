"""Direct unit tests for codegraph.parsers.typescript helpers."""
from __future__ import annotations

import tree_sitter

from codegraph.parsers.base import load_parser
from codegraph.parsers.typescript import (
    _extract_params,
    _extract_return_type,
    _object_top_level_keys,
    _strip_quotes,
)

# ---------------------------------------------------------------------------
# _strip_quotes — pure string helper
# ---------------------------------------------------------------------------


def test_strip_quotes_double() -> None:
    assert _strip_quotes('"hello"') == "hello"


def test_strip_quotes_single() -> None:
    assert _strip_quotes("'world'") == "world"


def test_strip_quotes_backtick() -> None:
    assert _strip_quotes("`tmpl`") == "tmpl"


def test_strip_quotes_unquoted_passthrough() -> None:
    assert _strip_quotes("plain") == "plain"


def test_strip_quotes_mismatched_left_only() -> None:
    assert _strip_quotes('"abc') == '"abc'


def test_strip_quotes_mismatched_pair() -> None:
    # Opening " but closing ' — mismatch, no strip
    assert _strip_quotes("\"abc'") == "\"abc'"


def test_strip_quotes_empty_string() -> None:
    assert _strip_quotes("") == ""


def test_strip_quotes_single_char() -> None:
    assert _strip_quotes('"') == '"'


# ---------------------------------------------------------------------------
# Tree-sitter dependent helpers — use a real TS parser
# ---------------------------------------------------------------------------


def _parse_ts(source: str) -> tuple[tree_sitter.Tree, bytes]:
    parser = load_parser("typescript")
    src_bytes = source.encode("utf-8")
    return parser.parse(src_bytes), src_bytes


def _find_first(node: tree_sitter.Node, type_name: str) -> tree_sitter.Node | None:
    if node.type == type_name:
        return node
    for c in node.children:
        found = _find_first(c, type_name)
        if found is not None:
            return found
    return None


def test_object_top_level_keys_basic() -> None:
    tree, src = _parse_ts("const x = { a: 1, b: 2, c: 3 };")
    obj = _find_first(tree.root_node, "object")
    assert obj is not None
    keys = _object_top_level_keys(obj, src)
    assert keys == ["a", "b", "c"]


def test_object_top_level_keys_string_keys_stripped() -> None:
    tree, src = _parse_ts('const x = { "a": 1, "b": 2 };')
    obj = _find_first(tree.root_node, "object")
    assert obj is not None
    keys = _object_top_level_keys(obj, src)
    assert keys == ["a", "b"]


def test_object_top_level_keys_shorthand() -> None:
    tree, src = _parse_ts("const a = 1; const b = 2; const x = { a, b };")
    # Find the *last* object node — first may be other constructs.
    objs: list[tree_sitter.Node] = []

    def walk(n: tree_sitter.Node) -> None:
        if n.type == "object":
            objs.append(n)
        for c in n.children:
            walk(c)

    walk(tree.root_node)
    assert objs
    keys = _object_top_level_keys(objs[-1], src)
    assert "a" in keys and "b" in keys


def test_object_top_level_keys_non_object_returns_empty() -> None:
    tree, src = _parse_ts("const x = 42;")
    # Pass the entire root_node — _object_top_level_keys checks type=="object".
    keys = _object_top_level_keys(tree.root_node, src)
    assert keys == []


def test_object_top_level_keys_empty_object() -> None:
    tree, src = _parse_ts("const x = {};")
    obj = _find_first(tree.root_node, "object")
    assert obj is not None
    assert _object_top_level_keys(obj, src) == []


# ---------------------------------------------------------------------------
# _extract_params
# ---------------------------------------------------------------------------


def _find_function(tree: tree_sitter.Tree) -> tree_sitter.Node | None:
    return _find_first(tree.root_node, "function_declaration")


def test_extract_params_none_node() -> None:
    assert _extract_params(None, b"") == []


def test_extract_params_simple_typed() -> None:
    tree, src = _parse_ts("function f(a: number, b: string): void {}")
    fn = _find_function(tree)
    assert fn is not None
    params_node = fn.child_by_field_name("parameters")
    out = _extract_params(params_node, src)
    names = [p["name"] for p in out]
    assert "a" in names and "b" in names


def test_extract_params_no_params() -> None:
    tree, src = _parse_ts("function f(): void {}")
    fn = _find_function(tree)
    assert fn is not None
    params_node = fn.child_by_field_name("parameters")
    assert _extract_params(params_node, src) == []


def test_extract_params_with_default() -> None:
    tree, src = _parse_ts("function f(a: number = 5): void {}")
    fn = _find_function(tree)
    assert fn is not None
    params_node = fn.child_by_field_name("parameters")
    out = _extract_params(params_node, src)
    assert len(out) == 1
    assert out[0]["name"] == "a"


# ---------------------------------------------------------------------------
# _extract_return_type
# ---------------------------------------------------------------------------


def test_extract_return_type_explicit() -> None:
    tree, src = _parse_ts("function f(a: number): string { return ''; }")
    fn = _find_function(tree)
    assert fn is not None
    params_node = fn.child_by_field_name("parameters")
    rt = _extract_return_type(fn, params_node, src)
    assert rt == "string"


def test_extract_return_type_missing() -> None:
    tree, src = _parse_ts("function f(a: number) { return 1; }")
    fn = _find_function(tree)
    assert fn is not None
    params_node = fn.child_by_field_name("parameters")
    rt = _extract_return_type(fn, params_node, src)
    assert rt is None


def test_extract_return_type_complex_generic() -> None:
    tree, src = _parse_ts("function f(): Promise<number> { return Promise.resolve(1); }")
    fn = _find_function(tree)
    assert fn is not None
    params_node = fn.child_by_field_name("parameters")
    rt = _extract_return_type(fn, params_node, src)
    assert rt is not None
    assert "Promise" in rt
