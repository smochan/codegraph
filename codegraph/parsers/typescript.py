"""TypeScript/TSX/JavaScript extractor using tree-sitter."""
from __future__ import annotations

import re
from pathlib import Path, PurePosixPath
from typing import Any

import tree_sitter

from codegraph.graph.schema import Edge, EdgeKind, Node, NodeKind, make_node_id
from codegraph.parsers.base import (
    ExtractorBase,
    load_parser,
    node_text,
    register_extractor,
)

_TEST_RE = re.compile(r"\.(test|spec)\.(ts|tsx|js|jsx|mjs|cjs)$")
_TEST_DIR_RE = re.compile(r"(^|[/\\])__tests__[/\\]")

EXT_TO_LANG: dict[str, str] = {
    ".ts": "typescript",
    ".tsx": "tsx",
    ".js": "javascript",
    ".jsx": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
}


def _is_test_file(rel_path: str) -> bool:
    return bool(_TEST_RE.search(rel_path) or _TEST_DIR_RE.search(rel_path))


# --- Public-API pragma detection ----------------------------------------
#
# A TypeScript/JavaScript function, method, or class is exempted from
# dead-code analysis by an immediately-preceding line comment of the form
# ``// pragma: codegraph-public-api`` or ``// codegraph: public-api``.
_PUBLIC_API_PRAGMAS_TS: tuple[str, ...] = (
    "// pragma: codegraph-public-api",
    "// codegraph: public-api",
)


def _line_has_public_api_pragma_ts(line: str) -> bool:
    stripped = line.strip()
    return any(pragma in stripped for pragma in _PUBLIC_API_PRAGMAS_TS)


def _has_public_api_pragma_ts(def_node: tree_sitter.Node, src: bytes) -> bool:
    """Return True if a TS def/class is preceded by a public-API pragma.

    Mirrors the Python helper: walks backward past blank lines from the
    definition's start byte and matches the first non-blank line against
    the pragma forms. Same-line trailing pragmas are also accepted.
    Walks through ``export_statement`` wrappers so a pragma above an
    ``export function foo()`` declaration is honored.
    """
    container: tree_sitter.Node = def_node
    parent = def_node.parent
    while parent is not None and parent.type in (
        "export_statement", "ambient_declaration",
    ):
        container = parent
        parent = parent.parent
    start_byte = container.start_byte

    sig_end = src.find(b"\n", start_byte)
    if sig_end == -1:
        sig_end = container.end_byte
    sig_line = src[start_byte:sig_end].decode("utf-8", errors="replace")
    if _line_has_public_api_pragma_ts(sig_line):
        return True

    cursor = start_byte
    if cursor > 0 and src[cursor - 1:cursor] == b"\n":
        cursor -= 1
    while cursor > 0:
        prev_nl = src.rfind(b"\n", 0, cursor)
        line_start = prev_nl + 1 if prev_nl != -1 else 0
        line = src[line_start:cursor].decode("utf-8", errors="replace")
        if not line.strip():
            cursor = prev_nl
            if cursor <= 0:
                return False
            continue
        return _line_has_public_api_pragma_ts(line)
    return False


def _file_to_qualname(rel_path: str) -> str:
    p = PurePosixPath(rel_path)
    stem = str(p.with_suffix(""))
    return stem.replace("/", ".")


def _extract_string(node: tree_sitter.Node, src: bytes) -> str:
    text = node_text(node, src)
    return text.strip("'\"` ")


_HTTP_VERBS = {"get", "post", "put", "delete", "patch", "head", "options"}


def _strip_quotes(text: str) -> str:
    if len(text) >= 2 and text[0] in "'\"`" and text[-1] == text[0]:
        return text[1:-1]
    return text


def _object_top_level_keys(obj_node: tree_sitter.Node, src: bytes) -> list[str]:
    """Return the top-level keys of an object literal as a list of strings.

    Handles `pair` (key: value) and `shorthand_property_identifier` shapes.
    Spread elements and computed keys are skipped.
    """
    keys: list[str] = []
    if obj_node.type != "object":
        return keys
    for pair in obj_node.children:
        if pair.type == "pair":
            key_node = pair.child_by_field_name("key")
            if key_node is None:
                key_node = next(
                    (
                        c for c in pair.children
                        if c.type in ("property_identifier", "string", "identifier")
                    ),
                    None,
                )
            if key_node is None:
                continue
            text = node_text(key_node, src)
            if key_node.type == "string":
                text = _strip_quotes(text)
            keys.append(text)
        elif pair.type == "shorthand_property_identifier":
            keys.append(node_text(pair, src))
    return keys


def _extract_body_keys_from_init(
    init_node: tree_sitter.Node, src: bytes
) -> list[str]:
    """Given a fetch `init` object literal, extract body_keys.

    Looks for `body: <value>` where <value> is either an object literal or
    `JSON.stringify(<object literal>)`. Returns the top-level keys of that
    object, or an empty list if not extractable.
    """
    if init_node.type != "object":
        return []
    for pair in init_node.children:
        if pair.type != "pair":
            continue
        key_node = pair.child_by_field_name("key")
        if key_node is None:
            continue
        key_text = node_text(key_node, src)
        if key_node.type == "string":
            key_text = _strip_quotes(key_text)
        if key_text != "body":
            continue
        value_node = pair.child_by_field_name("value")
        if value_node is None:
            named = [c for c in pair.children if c.is_named]
            if len(named) >= 2:
                value_node = named[-1]
        if value_node is None:
            return []
        if value_node.type == "object":
            return _object_top_level_keys(value_node, src)
        if value_node.type == "call_expression":
            func = value_node.child_by_field_name("function")
            if func is not None and node_text(func, src) == "JSON.stringify":
                args = value_node.child_by_field_name("arguments")
                if args is not None:
                    inner = next(
                        (c for c in args.children if c.is_named), None
                    )
                    if inner is not None and inner.type == "object":
                        return _object_top_level_keys(inner, src)
        return []
    return []


def _extract_method_from_init(
    init_node: tree_sitter.Node, src: bytes
) -> str | None:
    """Pull `method: "POST"` (or similar) from a fetch init object literal."""
    if init_node.type != "object":
        return None
    for pair in init_node.children:
        if pair.type != "pair":
            continue
        key_node = pair.child_by_field_name("key")
        if key_node is None:
            continue
        key_text = node_text(key_node, src)
        if key_node.type == "string":
            key_text = _strip_quotes(key_text)
        if key_text != "method":
            continue
        value_node = pair.child_by_field_name("value")
        if value_node is None:
            named = [c for c in pair.children if c.is_named]
            if len(named) >= 2:
                value_node = named[-1]
        if value_node is None:
            return None
        if value_node.type == "string":
            return _strip_quotes(node_text(value_node, src)).upper()
        return None
    return None


def _classify_url_node(
    url_node: tree_sitter.Node | None, src: bytes
) -> tuple[str, str]:
    """Return (url_text, url_kind) for a URL argument node.

    url_kind is one of: "literal", "template", "dynamic".
    For literals the text is unquoted; for templates the raw source (incl.
    backticks and `${...}` placeholders) is preserved verbatim; for any
    other expression, the kind is "dynamic" and the text is the source.
    """
    if url_node is None:
        return "", "dynamic"
    if url_node.type == "string":
        return _strip_quotes(node_text(url_node, src)), "literal"
    if url_node.type == "template_string":
        return node_text(url_node, src), "template"
    return node_text(url_node, src), "dynamic"


_SIMPLE_EXPR_TYPES = {
    "identifier",
    "string",
    "number",
    "true",
    "false",
    "null",
    "undefined",
    "member_expression",
    "subscript_expression",
    "this",
    "super",
}


def _strip_type_annotation(text: str) -> str:
    """Remove the leading colon (and whitespace) from a type_annotation text."""
    s = text.lstrip()
    if s.startswith(":"):
        s = s[1:]
    return s.strip()


def _extract_param(
    p: tree_sitter.Node, src: bytes
) -> dict[str, str | None] | None:
    """Extract a single parameter from a `required_parameter`/`optional_parameter`
    or any pattern node. Returns dict with name/type/default or None to skip.
    """
    name: str | None = None
    type_text: str | None = None
    default_text: str | None = None
    saw_eq = False
    for c in p.children:
        ct = c.type
        if ct == "=":
            saw_eq = True
            continue
        if saw_eq:
            # Default value expression follows '='.
            if c.is_named:
                default_text = node_text(c, src)
            continue
        if ct == "identifier" and name is None:
            name = node_text(c, src)
        elif ct == "rest_pattern":
            # `...rest` -> name = "...rest"
            inner = next(
                (cc for cc in c.children if cc.type == "identifier"),
                None,
            )
            name = (
                "..." + node_text(inner, src)
                if inner is not None
                else node_text(c, src)
            )
        elif ct == "type_annotation":
            type_text = _strip_type_annotation(node_text(c, src))
        elif ct in ("object_pattern", "array_pattern") and name is None:
            # Destructured params -> use the raw text as the "name".
            name = node_text(c, src)
        elif ct == "?":
            # Optional parameter marker; nothing to record beyond presence.
            continue
    if name is None:
        return None
    return {"name": name, "type": type_text, "default": default_text}


def _extract_params(
    params_node: tree_sitter.Node | None, src: bytes
) -> list[dict[str, str | None]]:
    if params_node is None:
        return []
    out: list[dict[str, str | None]] = []
    for c in params_node.children:
        if c.type in ("required_parameter", "optional_parameter"):
            p = _extract_param(c, src)
            if p is not None:
                out.append(p)
    return out


def _extract_return_type(
    func_node: tree_sitter.Node, params_node: tree_sitter.Node | None, src: bytes
) -> str | None:
    """Return the type annotation that follows `formal_parameters` inside a
    function / method / arrow declaration. Returns text without the leading
    colon, or None if absent.
    """
    # Prefer the named field on TS nodes when present.
    rt = func_node.child_by_field_name("return_type")
    if rt is not None and rt.type == "type_annotation":
        return _strip_type_annotation(node_text(rt, src))
    # Fallback: walk siblings after `formal_parameters` by start_byte.
    if params_node is None:
        return None
    after = False
    params_end = params_node.end_byte
    for c in func_node.children:
        if not after:
            if c.start_byte >= params_end:
                after = True
            else:
                continue
        if c.type == "type_annotation":
            return _strip_type_annotation(node_text(c, src))
        if c.type in ("statement_block", "=>"):
            return None
    return None


def _arg_text(node: tree_sitter.Node, src: bytes) -> str:
    """Return the text of an argument expression, simplified to '<expr>' if
    it is not in the allow-list of simple expression types.
    """
    if node.type in _SIMPLE_EXPR_TYPES:
        return node_text(node, src)
    return "<expr>"


def _split_call_arguments(
    args_node: tree_sitter.Node, src: bytes
) -> tuple[list[str], dict[str, str]]:
    """Walk the children of a `call_expression` `arguments` node and return
    (positional_args, kwargs).

    Rule for object-literal -> kwargs:
    Split a single object literal into kwargs only when there is exactly one
    object-literal argument AND it appears as the last positional argument
    (i.e. trailing options object). Otherwise the object literal is treated
    as a normal positional arg, simplified to its source text or `<expr>`.
    """
    # Collect named children (skip `(`, `)`, `,`).
    items: list[tree_sitter.Node] = [c for c in args_node.children if c.is_named]
    if not items:
        return [], {}

    object_indices = [i for i, n in enumerate(items) if n.type == "object"]
    last_idx = len(items) - 1
    split_kwargs = (
        len(object_indices) == 1 and object_indices[0] == last_idx
    )

    args: list[str] = []
    kwargs: dict[str, str] = {}

    for idx, n in enumerate(items):
        if n.type == "spread_element":
            # `...rest` -> "*rest"
            inner = next(
                (cc for cc in n.children if cc.is_named),
                None,
            )
            if inner is not None and inner.type == "identifier":
                args.append("*" + node_text(inner, src))
            else:
                args.append("*<expr>")
            continue
        if split_kwargs and idx == last_idx and n.type == "object":
            for pair in n.children:
                if pair.type != "pair":
                    continue
                key_node = pair.child_by_field_name("key")
                if key_node is None:
                    key_node = next(
                        (
                            c for c in pair.children
                            if c.type in (
                                "property_identifier", "string", "identifier"
                            )
                        ),
                        None,
                    )
                value_node = pair.child_by_field_name("value")
                if value_node is None:
                    # Last named child after the colon.
                    named = [c for c in pair.children if c.is_named]
                    if len(named) >= 2:
                        value_node = named[-1]
                if key_node is None or value_node is None:
                    continue
                key_text = node_text(key_node, src)
                if key_node.type == "string":
                    key_text = key_text.strip("'\"`")
                kwargs[key_text] = _arg_text(value_node, src)
            continue
        args.append(_arg_text(n, src))

    return args, kwargs


def _named_imports(
    clause: tree_sitter.Node | None, src: bytes
) -> list[str]:
    """Extract imported names from an import_clause.

    Handles default imports, named imports (`{ a, b as c }`), and namespace
    imports (`* as ns`). For aliased imports we record the *original* name
    so the resolver can bind the alias used in the source via the same
    full qualname.
    """
    if clause is None:
        return []
    names: list[str] = []
    for child in clause.children:
        if child.type == "identifier":
            # Default import: `import Foo from 'm'` -> 'Foo'.
            names.append(node_text(child, src))
        elif child.type == "named_imports":
            for spec in child.children:
                if spec.type != "import_specifier":
                    continue
                # First identifier inside specifier is the original name.
                first = next(
                    (c for c in spec.children if c.type == "identifier"),
                    None,
                )
                if first is not None:
                    names.append(node_text(first, src))
        elif child.type == "namespace_import":
            # `import * as ns from 'm'` -> bind `ns` to the module itself.
            ident = next(
                (c for c in child.children if c.type == "identifier"),
                None,
            )
            if ident is not None:
                # Namespace alias maps to the module, not a sub-name.
                # We skip per-name edges for namespace imports; the existing
                # source-level IMPORTS edge already covers the module.
                continue
    return names


@register_extractor
class TypeScriptExtractor(ExtractorBase):
    language = "typescript"
    extensions = (".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs")

    def parse_file(
        self, path: Path, repo_root: Path
    ) -> tuple[list[Node], list[Edge]]:
        src = path.read_bytes()
        rel = path.relative_to(repo_root).as_posix()
        ext = path.suffix.lower()
        lang_key = EXT_TO_LANG.get(ext, "typescript")
        parser = load_parser(lang_key)
        tree = parser.parse(src)
        root = tree.root_node

        nodes: list[Node] = []
        edges: list[Edge] = []

        is_test = _is_test_file(rel)
        qualname = _file_to_qualname(rel)
        module_id = make_node_id(NodeKind.MODULE, qualname, rel)
        module_node = Node(
            id=module_id,
            kind=NodeKind.MODULE,
            name=path.stem,
            qualname=qualname,
            file=rel,
            line_start=1,
            line_end=root.end_point[0] + 1,
            language=lang_key,
            metadata={"is_test": is_test},
        )
        nodes.append(module_node)

        if is_test:
            test_id = make_node_id(NodeKind.TEST, qualname, rel)
            test_node = Node(
                id=test_id,
                kind=NodeKind.TEST,
                name=path.stem,
                qualname=qualname,
                file=rel,
                line_start=1,
                line_end=root.end_point[0] + 1,
                language=lang_key,
                metadata={"is_test": True},
            )
            nodes.append(test_node)

        self._visit(root, rel, qualname, module_id, lang_key, src, nodes, edges)
        self._collect_require_imports(root, rel, module_id, src, edges)
        express_routes = self._collect_express_routes(root, src)
        if express_routes:
            module_node.metadata["express_routes"] = express_routes
        return nodes, edges

    def _collect_express_routes(
        self, root: tree_sitter.Node, src: bytes,
    ) -> list[dict[str, Any]]:
        """Find Express/Koa-style route registrations anywhere in the tree.

        Matches ``app.get('/x', fn)``, ``router.post('/y', mw, fn)``, etc.
        Returns a list of ``{"method", "path", "handler_name", "line"}``
        dicts which is stored on the module node's metadata for downstream
        consumption by ``codegraph.analysis.infrastructure``.
        """
        verbs = {"get", "post", "put", "delete", "patch", "head", "options", "all"}
        out: list[dict[str, Any]] = []
        stack: list[tree_sitter.Node] = [root]
        while stack:
            node = stack.pop()
            if node.type == "call_expression":
                func_child = node.child_by_field_name("function")
                if func_child is not None and func_child.type == "member_expression":
                    obj_node = func_child.child_by_field_name("object")
                    prop_node = func_child.child_by_field_name("property")
                    receiver = node_text(obj_node, src) if obj_node else ""
                    verb = node_text(prop_node, src).lower() if prop_node else ""
                    receiver_lc = receiver.lower()
                    if (
                        verb in verbs
                        and (
                            "router" in receiver_lc
                            or "app" in receiver_lc
                            or "api" in receiver_lc
                            or receiver_lc in ("v1", "v2")
                        )
                    ):
                        args_node = node.child_by_field_name("arguments")
                        if args_node is None:
                            for c in node.children:
                                if c.type == "arguments":
                                    args_node = c
                                    break
                        if args_node is not None:
                            arg_children = [
                                c for c in args_node.children
                                if c.type not in (",", "(", ")")
                            ]
                            if arg_children and arg_children[0].type in (
                                "string", "template_string",
                            ):
                                path_text = _extract_string(arg_children[0], src) \
                                    if arg_children[0].type == "string" \
                                    else node_text(arg_children[0], src).strip("`")
                                handler_name = ""
                                for c in arg_children[1:]:
                                    if c.type == "identifier":
                                        handler_name = node_text(c, src)
                                    elif c.type in (
                                        "arrow_function", "function",
                                        "function_expression",
                                    ):
                                        handler_name = ""
                                        break
                                out.append({
                                    "method": verb.upper(),
                                    "path": path_text,
                                    "handler_name": handler_name,
                                    "line": node.start_point[0] + 1,
                                })
            stack.extend(node.children)
        return out

    def _collect_require_imports(
        self,
        root: tree_sitter.Node,
        rel: str,
        module_id: str,
        src: bytes,
        edges: list[Edge],
    ) -> None:
        """Capture CommonJS ``require("x")`` and dynamic ``import("x")`` as
        IMPORTS edges. Walks the whole tree once. Idempotent against the
        ES-import handler — those run on ``import_statement`` nodes which
        this loop ignores.
        """
        stack: list[tree_sitter.Node] = [root]
        while stack:
            node = stack.pop()
            if node.type == "call_expression":
                func_child = node.child_by_field_name("function")
                if func_child is None and node.children:
                    func_child = node.children[0]
                fn_name = node_text(func_child, src) if func_child else ""
                if fn_name in ("require", "import"):
                    args_node = node.child_by_field_name("arguments")
                    if args_node is None:
                        for c in node.children:
                            if c.type == "arguments":
                                args_node = c
                                break
                    target = ""
                    if args_node is not None:
                        for c in args_node.children:
                            if c.type == "string":
                                target = _extract_string(c, src)
                                break
                    if target:
                        edges.append(Edge(
                            src=module_id,
                            dst=f"unresolved::{target}",
                            kind=EdgeKind.IMPORTS,
                            file=rel,
                            line=node.start_point[0] + 1,
                            metadata={
                                "source": target,
                                "target_name": target,
                                "via": fn_name,
                            },
                        ))
            stack.extend(node.children)

    def _visit(
        self,
        block: tree_sitter.Node,
        rel: str,
        parent_qualname: str,
        parent_id: str,
        lang: str,
        src: bytes,
        nodes: list[Node],
        edges: list[Edge],
    ) -> None:
        for child in block.children:
            ct = child.type
            if ct == "import_statement":
                self._handle_import(child, rel, parent_id, src, edges)
            elif ct in ("class_declaration", "abstract_class_declaration"):
                self._handle_class(
                    child, rel, parent_qualname, parent_id, lang, src, nodes, edges
                )
            elif ct == "function_declaration":
                self._handle_function_decl(
                    child, rel, parent_qualname, parent_id, lang, src, nodes, edges
                )
            elif ct in ("lexical_declaration", "variable_declaration"):
                self._handle_lexical_decl(
                    child, rel, parent_qualname, parent_id, lang, src, nodes, edges
                )
            elif ct == "export_statement":
                for sub in child.children:
                    if sub.type in (
                        "class_declaration", "abstract_class_declaration"
                    ):
                        self._handle_class(
                            sub, rel, parent_qualname, parent_id, lang,
                            src, nodes, edges,
                        )
                    elif sub.type == "function_declaration":
                        self._handle_function_decl(
                            sub, rel, parent_qualname, parent_id, lang,
                            src, nodes, edges,
                        )
                    elif sub.type in (
                        "lexical_declaration", "variable_declaration"
                    ):
                        self._handle_lexical_decl(
                            sub, rel, parent_qualname, parent_id, lang,
                            src, nodes, edges,
                        )

    def _handle_import(
        self,
        node: tree_sitter.Node,
        rel: str,
        parent_id: str,
        src: bytes,
        edges: list[Edge],
    ) -> None:
        source_node: tree_sitter.Node | None = None
        clause_node: tree_sitter.Node | None = None
        for child in node.children:
            if child.type == "string" and source_node is None:
                source_node = child
            elif child.type == "import_clause":
                clause_node = child
        if source_node is None:
            return
        source = _extract_string(source_node, src)
        line = node.start_point[0] + 1
        named = _named_imports(clause_node, src)

        # When there are no named imports (e.g. `import './side-effect'`,
        # `import * as ns from './m'`), keep the module-level edge. When we
        # have per-name edges, they carry binding info and the module-level
        # edge would be redundant noise.
        if not named:
            edges.append(Edge(
                src=parent_id,
                dst=f"unresolved::{source}",
                kind=EdgeKind.IMPORTS,
                file=rel,
                line=line,
                metadata={"source": source, "target_name": source},
            ))

        for imported_name in named:
            edges.append(Edge(
                src=parent_id,
                dst=f"unresolved::{source}.{imported_name}",
                kind=EdgeKind.IMPORTS,
                file=rel,
                line=line,
                metadata={
                    "source": source,
                    "target_name": f"{source}.{imported_name}",
                    "imported_name": imported_name,
                },
            ))

    def _handle_class(
        self,
        node: tree_sitter.Node,
        rel: str,
        parent_qualname: str,
        parent_id: str,
        lang: str,
        src: bytes,
        nodes: list[Node],
        edges: list[Edge],
    ) -> None:
        name_node = node.child_by_field_name("name")
        if name_node is None:
            for c in node.children:
                if c.type == "type_identifier":
                    name_node = c
                    break
        if name_node is None:
            return
        name = node_text(name_node, src)
        qualname = f"{parent_qualname}.{name}" if parent_qualname else name
        class_id = make_node_id(NodeKind.CLASS, qualname, rel)

        cls_md: dict[str, Any] = {}
        if _has_public_api_pragma_ts(node, src):
            cls_md["public_api"] = True
        class_node = Node(
            id=class_id,
            kind=NodeKind.CLASS,
            name=name,
            qualname=qualname,
            file=rel,
            line_start=node.start_point[0] + 1,
            line_end=node.end_point[0] + 1,
            language=lang,
            metadata=cls_md,
        )
        nodes.append(class_node)

        edges.append(Edge(
            src=class_id, dst=parent_id, kind=EdgeKind.DEFINED_IN,
            file=rel, line=node.start_point[0] + 1,
        ))

        for child in node.children:
            if child.type == "class_heritage":
                for sub in child.children:
                    if sub.type == "extends_clause":
                        for base in sub.children:
                            if base.is_named and base.type in (
                                "identifier", "member_expression",
                                "type_identifier",
                            ):
                                base_name = node_text(base, src)
                                edges.append(Edge(
                                    src=class_id,
                                    dst=f"unresolved::{base_name}",
                                    kind=EdgeKind.INHERITS,
                                    file=rel,
                                    line=node.start_point[0] + 1,
                                    metadata={"target_name": base_name},
                                ))
                    elif sub.type == "implements_clause":
                        for base in sub.children:
                            if base.is_named and base.type in (
                                "identifier", "type_identifier",
                                "generic_type",
                            ):
                                base_name = node_text(base, src)
                                edges.append(Edge(
                                    src=class_id,
                                    dst=f"unresolved::{base_name}",
                                    kind=EdgeKind.IMPLEMENTS,
                                    file=rel,
                                    line=node.start_point[0] + 1,
                                    metadata={"target_name": base_name},
                                ))

        body = node.child_by_field_name("body")
        if body is None:
            for c in node.children:
                if c.type == "class_body":
                    body = c
                    break
        if body is not None:
            for child in body.children:
                if child.type == "method_definition":
                    self._handle_method(
                        child, rel, qualname, class_id, lang, src, nodes, edges
                    )

    def _handle_method(
        self,
        node: tree_sitter.Node,
        rel: str,
        parent_qualname: str,
        parent_id: str,
        lang: str,
        src: bytes,
        nodes: list[Node],
        edges: list[Edge],
    ) -> None:
        name_node = node.child_by_field_name("name")
        if name_node is None:
            for c in node.children:
                if c.type in ("property_identifier", "identifier"):
                    name_node = c
                    break
        if name_node is None:
            return
        name = node_text(name_node, src)
        qualname = f"{parent_qualname}.{name}"
        method_id = make_node_id(NodeKind.METHOD, qualname, rel)

        params = node.child_by_field_name("parameters")
        sig = f"{name}{node_text(params, src)}" if params is not None else name
        params_list = _extract_params(params, src)
        return_type = _extract_return_type(node, params, src)

        method_md: dict[str, Any] = {
            "params": params_list,
            "returns": return_type,
        }
        if _has_public_api_pragma_ts(node, src):
            method_md["public_api"] = True
        method_node = Node(
            id=method_id,
            kind=NodeKind.METHOD,
            name=name,
            qualname=qualname,
            file=rel,
            line_start=node.start_point[0] + 1,
            line_end=node.end_point[0] + 1,
            signature=sig,
            language=lang,
            metadata=method_md,
        )
        nodes.append(method_node)

        edges.append(Edge(
            src=method_id, dst=parent_id, kind=EdgeKind.DEFINED_IN,
            file=rel, line=node.start_point[0] + 1,
        ))

        body = node.child_by_field_name("body")
        if body is not None:
            self._collect_calls(body, rel, method_id, src, edges)
            self._collect_fetches(body, rel, method_id, src, nodes, edges)

    def _handle_function_decl(
        self,
        node: tree_sitter.Node,
        rel: str,
        parent_qualname: str,
        parent_id: str,
        lang: str,
        src: bytes,
        nodes: list[Node],
        edges: list[Edge],
    ) -> None:
        name_node = node.child_by_field_name("name")
        if name_node is None:
            for c in node.children:
                if c.type == "identifier":
                    name_node = c
                    break
        if name_node is None:
            return
        name = node_text(name_node, src)
        qualname = f"{parent_qualname}.{name}" if parent_qualname else name
        func_id = make_node_id(NodeKind.FUNCTION, qualname, rel)

        params = node.child_by_field_name("parameters")
        sig = f"{name}{node_text(params, src)}" if params is not None else name
        params_list = _extract_params(params, src)
        return_type = _extract_return_type(node, params, src)

        func_md: dict[str, Any] = {
            "params": params_list,
            "returns": return_type,
        }
        if _has_public_api_pragma_ts(node, src):
            func_md["public_api"] = True
        func_node = Node(
            id=func_id,
            kind=NodeKind.FUNCTION,
            name=name,
            qualname=qualname,
            file=rel,
            line_start=node.start_point[0] + 1,
            line_end=node.end_point[0] + 1,
            signature=sig,
            language=lang,
            metadata=func_md,
        )
        nodes.append(func_node)

        edges.append(Edge(
            src=func_id, dst=parent_id, kind=EdgeKind.DEFINED_IN,
            file=rel, line=node.start_point[0] + 1,
        ))

        body = node.child_by_field_name("body")
        if body is not None:
            self._collect_calls(body, rel, func_id, src, edges)
            self._collect_fetches(body, rel, func_id, src, nodes, edges)

    def _handle_lexical_decl(
        self,
        node: tree_sitter.Node,
        rel: str,
        parent_qualname: str,
        parent_id: str,
        lang: str,
        src: bytes,
        nodes: list[Node],
        edges: list[Edge],
    ) -> None:
        for child in node.children:
            if child.type != "variable_declarator":
                continue
            name_node = child.child_by_field_name("name")
            if name_node is None:
                for c in child.children:
                    if c.type == "identifier":
                        name_node = c
                        break
            value_node = child.child_by_field_name("value")
            if (
                name_node is not None
                and value_node is not None
                and value_node.type in ("arrow_function", "function", "function_expression")
            ):
                name = node_text(name_node, src)
                qualname = (
                    f"{parent_qualname}.{name}" if parent_qualname else name
                )
                func_id = make_node_id(NodeKind.FUNCTION, qualname, rel)

                arrow_params = value_node.child_by_field_name("parameters")
                if arrow_params is None:
                    for c in value_node.children:
                        if c.type == "formal_parameters":
                            arrow_params = c
                            break
                params_list = _extract_params(arrow_params, src)
                return_type = _extract_return_type(
                    value_node, arrow_params, src
                )

                func_node = Node(
                    id=func_id,
                    kind=NodeKind.FUNCTION,
                    name=name,
                    qualname=qualname,
                    file=rel,
                    line_start=node.start_point[0] + 1,
                    line_end=node.end_point[0] + 1,
                    language=lang,
                    metadata={
                        "arrow": True,
                        "params": params_list,
                        "returns": return_type,
                    },
                )
                nodes.append(func_node)

                edges.append(Edge(
                    src=func_id, dst=parent_id, kind=EdgeKind.DEFINED_IN,
                    file=rel, line=node.start_point[0] + 1,
                ))

                body = value_node.child_by_field_name("body")
                if body is not None:
                    self._collect_calls(body, rel, func_id, src, edges)
                    self._collect_fetches(body, rel, func_id, src, nodes, edges)

    def _collect_calls(
        self,
        node: tree_sitter.Node,
        rel: str,
        scope_id: str,
        src: bytes,
        edges: list[Edge],
    ) -> None:
        stack: list[tree_sitter.Node] = list(node.children)
        while stack:
            child = stack.pop()
            if child.type == "call_expression":
                func_child = child.child_by_field_name("function")
                if func_child is None and child.children:
                    func_child = child.children[0]
                if func_child is not None:
                    name = node_text(func_child, src)
                    args_node = child.child_by_field_name("arguments")
                    if args_node is None:
                        for c in child.children:
                            if c.type == "arguments":
                                args_node = c
                                break
                    if args_node is not None:
                        call_args, call_kwargs = _split_call_arguments(
                            args_node, src
                        )
                    else:
                        call_args, call_kwargs = [], {}
                    edges.append(Edge(
                        src=scope_id,
                        dst=f"unresolved::{name}",
                        kind=EdgeKind.CALLS,
                        file=rel,
                        line=child.start_point[0] + 1,
                        metadata={
                            "target_name": name,
                            "args": call_args,
                            "kwargs": call_kwargs,
                        },
                    ))
            stack.extend(child.children)

    # ------------------------------------------------------------------
    # DF2: HTTP call-site detection (fetch / axios / SWR / api-clients)
    # ------------------------------------------------------------------

    def _collect_fetches(
        self,
        node: tree_sitter.Node,
        rel: str,
        scope_id: str,
        src: bytes,
        nodes: list[Node],
        edges: list[Edge],
    ) -> None:
        """Walk the function body and emit FETCH_CALL edges for HTTP call sites.

        Recognised patterns:
          fetch(url, init?)                    library=fetch
          axios.get/post/put/delete/patch(...) library=axios
          axios({ method, url, data })         library=axios
          useSWR(url, fetcher)                 library=swr  (treated as GET)
          useQuery({ queryKey, queryFn })      library=tanstack (best-effort)
          apiClient.get/post/put/delete(url)   library=apiclient (any ident)
        """
        stack: list[tree_sitter.Node] = list(node.children)
        while stack:
            child = stack.pop()
            if child.type == "call_expression":
                self._maybe_emit_fetch(child, rel, scope_id, src, nodes, edges)
            stack.extend(child.children)

    def _maybe_emit_fetch(
        self,
        call_node: tree_sitter.Node,
        rel: str,
        scope_id: str,
        src: bytes,
        nodes: list[Node],
        edges: list[Edge],
    ) -> None:
        func_child = call_node.child_by_field_name("function")
        if func_child is None and call_node.children:
            func_child = call_node.children[0]
        if func_child is None:
            return
        args_node = call_node.child_by_field_name("arguments")
        if args_node is None:
            for c in call_node.children:
                if c.type == "arguments":
                    args_node = c
                    break
        if args_node is None:
            return
        named_args: list[tree_sitter.Node] = [
            c for c in args_node.children if c.is_named
        ]

        line = call_node.start_point[0] + 1

        # --- fetch(url, init?) ---
        if func_child.type == "identifier" and node_text(func_child, src) == "fetch":
            if not named_args:
                return
            url_node = named_args[0]
            init_node = named_args[1] if len(named_args) >= 2 else None
            method = "GET"
            body_keys: list[str] = []
            if init_node is not None and init_node.type == "object":
                m = _extract_method_from_init(init_node, src)
                if m:
                    method = m
                body_keys = _extract_body_keys_from_init(init_node, src)
            self._emit_fetch_edge(
                rel, scope_id, line, method, url_node,
                "fetch", body_keys, src, nodes, edges,
            )
            return

        # --- useSWR(url, fetcher) ---
        if (
            func_child.type == "identifier"
            and node_text(func_child, src) == "useSWR"
            and named_args
        ):
            self._emit_fetch_edge(
                rel, scope_id, line, "GET", named_args[0],
                "swr", [], src, nodes, edges,
            )
            return

        # --- axios(config) — identifier call with single object arg ---
        if (
            func_child.type == "identifier"
            and node_text(func_child, src) == "axios"
            and named_args
            and named_args[0].type == "object"
        ):
            cfg = named_args[0]
            method = "GET"
            cfg_url_node: tree_sitter.Node | None = None
            body_keys = []
            for pair in cfg.children:
                if pair.type != "pair":
                    continue
                key_node = pair.child_by_field_name("key")
                if key_node is None:
                    continue
                key_text = node_text(key_node, src)
                if key_node.type == "string":
                    key_text = _strip_quotes(key_text)
                value_node = pair.child_by_field_name("value")
                if value_node is None:
                    nm = [c for c in pair.children if c.is_named]
                    if len(nm) >= 2:
                        value_node = nm[-1]
                if value_node is None:
                    continue
                if key_text == "method" and value_node.type == "string":
                    method = _strip_quotes(node_text(value_node, src)).upper()
                elif key_text == "url":
                    cfg_url_node = value_node
                elif key_text == "data" and value_node.type == "object":
                    body_keys = _object_top_level_keys(value_node, src)
            if cfg_url_node is not None:
                self._emit_fetch_edge(
                    rel, scope_id, line, method, cfg_url_node,
                    "axios", body_keys, src, nodes, edges,
                )
            return

        # --- useQuery({ queryKey, queryFn }) — best-effort ---
        if (
            func_child.type == "identifier"
            and node_text(func_child, src) == "useQuery"
            and named_args
            and named_args[0].type == "object"
        ):
            self._maybe_emit_useQuery(
                named_args[0], rel, scope_id, src, nodes, edges,
            )
            return

        # --- IDENT.METHOD(url, ...) — axios.get / apiClient.post / etc. ---
        if func_child.type == "member_expression":
            obj_node = func_child.child_by_field_name("object")
            prop_node = func_child.child_by_field_name("property")
            if obj_node is None or prop_node is None:
                return
            if obj_node.type != "identifier":
                return
            method_name = node_text(prop_node, src).lower()
            if method_name not in _HTTP_VERBS:
                return
            if not named_args:
                return
            url_node = named_args[0]
            # Only treat the first arg as a URL if it looks URL-ish.
            if url_node.type not in ("string", "template_string", "identifier"):
                return
            obj_name = node_text(obj_node, src)
            library = "axios" if obj_name == "axios" else "apiclient"
            method = method_name.upper()
            body_keys = []
            if (
                method in {"POST", "PUT", "PATCH"}
                and len(named_args) >= 2
                and named_args[1].type == "object"
            ):
                body_keys = _object_top_level_keys(named_args[1], src)
            self._emit_fetch_edge(
                rel, scope_id, line, method, url_node,
                library, body_keys, src, nodes, edges,
            )
            return

    def _maybe_emit_useQuery(
        self,
        cfg: tree_sitter.Node,
        rel: str,
        scope_id: str,
        src: bytes,
        nodes: list[Node],
        edges: list[Edge],
    ) -> None:
        """Best-effort: scan the queryFn body for a single fetch/axios call."""
        query_fn: tree_sitter.Node | None = None
        for pair in cfg.children:
            if pair.type != "pair":
                continue
            key_node = pair.child_by_field_name("key")
            if key_node is None:
                continue
            key_text = node_text(key_node, src)
            if key_node.type == "string":
                key_text = _strip_quotes(key_text)
            if key_text != "queryFn":
                continue
            value_node = pair.child_by_field_name("value")
            if value_node is None:
                nm = [c for c in pair.children if c.is_named]
                if len(nm) >= 2:
                    value_node = nm[-1]
            query_fn = value_node
            break
        if query_fn is None:
            return
        if query_fn.type not in ("arrow_function", "function", "function_expression"):
            return
        body = query_fn.child_by_field_name("body")
        if body is None:
            return
        # Walk and find the first fetch/axios call site; emit with library=tanstack.
        stack: list[tree_sitter.Node] = list(body.children) if body.is_named else [body]
        # When body is an expression (arrow shorthand), it itself may be the call.
        if body.type == "call_expression":
            stack = [body]
        else:
            stack = list(body.children)
            stack.append(body)
        for sub in stack:
            for desc in _walk(sub):
                if desc.type != "call_expression":
                    continue
                fc = desc.child_by_field_name("function")
                if fc is None:
                    continue
                if fc.type == "identifier" and node_text(fc, src) == "fetch":
                    args_node = desc.child_by_field_name("arguments")
                    if args_node is None:
                        continue
                    n_args = [c for c in args_node.children if c.is_named]
                    if not n_args:
                        continue
                    method = "GET"
                    body_keys: list[str] = []
                    if len(n_args) >= 2 and n_args[1].type == "object":
                        m = _extract_method_from_init(n_args[1], src)
                        if m:
                            method = m
                        body_keys = _extract_body_keys_from_init(n_args[1], src)
                    self._emit_fetch_edge(
                        rel, scope_id, desc.start_point[0] + 1, method,
                        n_args[0], "tanstack", body_keys, src, nodes, edges,
                    )
                    return
                if fc.type == "member_expression":
                    obj = fc.child_by_field_name("object")
                    prop = fc.child_by_field_name("property")
                    if (
                        obj is not None and prop is not None
                        and obj.type == "identifier"
                        and node_text(obj, src) == "axios"
                        and node_text(prop, src).lower() in _HTTP_VERBS
                    ):
                        args_node = desc.child_by_field_name("arguments")
                        if args_node is None:
                            continue
                        n_args = [c for c in args_node.children if c.is_named]
                        if not n_args:
                            continue
                        method = node_text(prop, src).upper()
                        body_keys = []
                        if (
                            method in {"POST", "PUT", "PATCH"}
                            and len(n_args) >= 2
                            and n_args[1].type == "object"
                        ):
                            body_keys = _object_top_level_keys(n_args[1], src)
                        self._emit_fetch_edge(
                            rel, scope_id, desc.start_point[0] + 1, method,
                            n_args[0], "tanstack", body_keys, src, nodes, edges,
                        )
                        return

    def _emit_fetch_edge(
        self,
        rel: str,
        scope_id: str,
        line: int,
        method: str,
        url_node: tree_sitter.Node,
        library: str,
        body_keys: list[str],
        src: bytes,
        nodes: list[Node],
        edges: list[Edge],
    ) -> None:
        url_text, url_kind = _classify_url_node(url_node, src)
        # Synthetic node id stable across files for the same (method, url).
        node_id = f"fetch::{method}::{url_text}"
        # De-duplicate synthetic nodes within this parse_file invocation.
        if not any(n.id == node_id for n in nodes):
            qn = f"fetch::{method}::{url_text}"
            nodes.append(Node(
                id=node_id,
                kind=NodeKind.VARIABLE,
                name=url_text or "<dynamic>",
                qualname=qn,
                file=rel,
                line_start=line,
                line_end=line,
                language="typescript",
                metadata={
                    "synthetic_kind": "FETCH_TARGET",
                    "method": method,
                    "url": url_text,
                    "url_kind": url_kind,
                },
            ))
        edge_md: dict[str, Any] = {
            "method": method,
            "url": url_text,
            "library": library,
            "body_keys": body_keys,
        }
        if url_kind != "literal":
            edge_md["url_kind"] = url_kind
        edges.append(Edge(
            src=scope_id,
            dst=node_id,
            kind=EdgeKind.FETCH_CALL,
            file=rel,
            line=line,
            metadata=edge_md,
        ))


def _walk(root: tree_sitter.Node) -> list[tree_sitter.Node]:
    """Iterative descendant walk including the root."""
    out: list[tree_sitter.Node] = []
    stack: list[tree_sitter.Node] = [root]
    while stack:
        n = stack.pop()
        out.append(n)
        stack.extend(n.children)
    return out
