"""Tests for codegraph.parsers.base.node_text and helpers."""
from __future__ import annotations

from codegraph.parsers.base import load_parser, node_text


def _parse_python(src: bytes):
    parser = load_parser("python")
    return parser.parse(src)


def test_node_text_extracts_byte_slice() -> None:
    src = b"x = 42\n"
    tree = _parse_python(src)
    root = tree.root_node
    # Text of the entire root spans the source.
    assert node_text(root, src) == "x = 42\n"


def test_node_text_returns_inner_slice() -> None:
    src = b"x = 42\n"
    tree = _parse_python(src)
    # First child is an assignment; its first child is the identifier 'x'.
    expr = tree.root_node.children[0]
    assign = expr.children[0]
    # Locate the identifier within the assignment subtree
    ident = next(
        (c for c in assign.children if c.type == "identifier"), None
    )
    assert ident is not None
    assert node_text(ident, src) == "x"


def test_node_text_handles_unicode_codepoints() -> None:
    # ensure multi-byte UTF-8 (emoji + latin) decodes properly
    src = "name = 'café 🚀'\n".encode()
    tree = _parse_python(src)
    text = node_text(tree.root_node, src)
    assert "café" in text
    assert "🚀" in text


def test_node_text_replaces_invalid_utf8() -> None:
    # Pass invalid utf-8 bytes via a fake span. We construct by parsing valid
    # source, then call node_text against an invalid byte buffer of same length.
    src = b"abc\n"
    tree = _parse_python(src)
    root = tree.root_node
    invalid = b"\xff\xfe\xfdz"  # length 4, all-invalid leading bytes
    out = node_text(root, invalid)
    # 'replace' mode never raises; result has the unicode replacement char
    assert isinstance(out, str)
    assert "�" in out


def test_node_text_empty_span_returns_empty_string() -> None:
    src = b""
    tree = _parse_python(src)
    assert node_text(tree.root_node, src) == ""
