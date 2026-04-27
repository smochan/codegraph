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


def _file_to_qualname(rel_path: str) -> str:
    p = PurePosixPath(rel_path)
    stem = str(p.with_suffix(""))
    return stem.replace("/", ".")


def _extract_string(node: tree_sitter.Node, src: bytes) -> str:
    text = node_text(node, src)
    return text.strip("'\"` ")


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

        class_node = Node(
            id=class_id,
            kind=NodeKind.CLASS,
            name=name,
            qualname=qualname,
            file=rel,
            line_start=node.start_point[0] + 1,
            line_end=node.end_point[0] + 1,
            language=lang,
            metadata={},
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
            metadata={"params": params_list, "returns": return_type},
        )
        nodes.append(method_node)

        edges.append(Edge(
            src=method_id, dst=parent_id, kind=EdgeKind.DEFINED_IN,
            file=rel, line=node.start_point[0] + 1,
        ))

        body = node.child_by_field_name("body")
        if body is not None:
            self._collect_calls(body, rel, method_id, src, edges)

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
            metadata={"params": params_list, "returns": return_type},
        )
        nodes.append(func_node)

        edges.append(Edge(
            src=func_id, dst=parent_id, kind=EdgeKind.DEFINED_IN,
            file=rel, line=node.start_point[0] + 1,
        ))

        body = node.child_by_field_name("body")
        if body is not None:
            self._collect_calls(body, rel, func_id, src, edges)

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
