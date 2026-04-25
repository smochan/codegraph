"""TypeScript/TSX/JavaScript extractor using tree-sitter."""
from __future__ import annotations

import re
from pathlib import Path, PurePosixPath

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
        return nodes, edges

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
        for child in node.children:
            if child.type == "string":
                source_node = child
                break
        if source_node is not None:
            source = _extract_string(source_node, src)
            edges.append(Edge(
                src=parent_id,
                dst=f"unresolved::{source}",
                kind=EdgeKind.IMPORTS,
                file=rel,
                line=node.start_point[0] + 1,
                metadata={"source": source, "target_name": source},
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
            metadata={},
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
            metadata={},
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

                func_node = Node(
                    id=func_id,
                    kind=NodeKind.FUNCTION,
                    name=name,
                    qualname=qualname,
                    file=rel,
                    line_start=node.start_point[0] + 1,
                    line_end=node.end_point[0] + 1,
                    language=lang,
                    metadata={"arrow": True},
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
                    edges.append(Edge(
                        src=scope_id,
                        dst=f"unresolved::{name}",
                        kind=EdgeKind.CALLS,
                        file=rel,
                        line=child.start_point[0] + 1,
                        metadata={"target_name": name},
                    ))
            stack.extend(child.children)
