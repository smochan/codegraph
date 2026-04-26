"""Python source extractor using tree-sitter."""
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


def _is_test_file(rel_path: str) -> bool:
    return bool(
        re.search(r"(^|[/\\])(tests?[/\\]|test_)", rel_path)
        or rel_path.endswith("_test.py")
    )


def _file_to_qualname(rel_path: str) -> str:
    """Convert repo-relative path like 'src/foo/bar.py' to 'src.foo.bar'."""
    p = PurePosixPath(rel_path)
    parts = list(p.with_suffix("").parts)
    if parts and parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def _get_docstring(block_node: tree_sitter.Node, src: bytes) -> str | None:
    for child in block_node.children:
        if child.type == "expression_statement":
            for sub in child.children:
                if sub.type == "string":
                    raw = node_text(sub, src).strip()
                    # Strip triple/single quotes
                    for q in ('"""', "'''", '"', "'"):
                        if raw.startswith(q) and raw.endswith(q):
                            raw = raw[len(q):-len(q)]
                            break
                    return raw.strip()
    return None


def _get_function_decorators(func_node: tree_sitter.Node, src: bytes) -> list[str]:
    decs: list[str] = []
    for child in func_node.children:
        if child.type == "decorator":
            decs.append(node_text(child, src))
    return decs


@register_extractor
class PythonExtractor(ExtractorBase):
    language = "python"
    extensions = (".py",)

    def parse_file(
        self, path: Path, repo_root: Path
    ) -> tuple[list[Node], list[Edge]]:
        src = path.read_bytes()
        rel = path.relative_to(repo_root).as_posix()
        parser = load_parser("python")
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
            name=qualname.split(".")[-1] if qualname else rel,
            qualname=qualname,
            file=rel,
            line_start=1,
            line_end=root.end_point[0] + 1,
            language="python",
            metadata={"is_test": is_test},
        )
        nodes.append(module_node)

        if is_test:
            test_id = make_node_id(NodeKind.TEST, qualname, rel)
            test_node = Node(
                id=test_id,
                kind=NodeKind.TEST,
                name=qualname.split(".")[-1] if qualname else rel,
                qualname=qualname,
                file=rel,
                line_start=1,
                line_end=root.end_point[0] + 1,
                language="python",
                metadata={"is_test": True},
            )
            nodes.append(test_node)

        self._visit_block(
            root, rel, qualname, module_id, None, src, nodes, edges
        )
        return nodes, edges

    def _visit_block(
        self,
        block: tree_sitter.Node,
        rel: str,
        parent_qualname: str,
        parent_id: str,
        enclosing_class_id: str | None,
        src: bytes,
        nodes: list[Node],
        edges: list[Edge],
    ) -> None:
        for child in block.children:
            if child.type == "class_definition":
                self._handle_class(
                    child, rel, parent_qualname, parent_id, src, nodes, edges
                )
            elif child.type == "function_definition":
                kind = (
                    NodeKind.METHOD if enclosing_class_id else NodeKind.FUNCTION
                )
                self._handle_function(
                    child, rel, parent_qualname, parent_id, kind,
                    src, nodes, edges,
                )
            elif child.type == "decorated_definition":
                inner = None
                for c in child.children:
                    if c.type in ("function_definition", "class_definition"):
                        inner = c
                        break
                if inner is not None and inner.type == "class_definition":
                    self._handle_class(
                        inner, rel, parent_qualname, parent_id,
                        src, nodes, edges,
                    )
                elif inner is not None:
                    kind = (
                        NodeKind.METHOD if enclosing_class_id else NodeKind.FUNCTION
                    )
                    self._handle_function(
                        inner, rel, parent_qualname, parent_id, kind,
                        src, nodes, edges,
                    )
            elif child.type == "import_statement":
                self._handle_import(child, rel, parent_id, src, edges)
            elif child.type == "import_from_statement":
                self._handle_import_from(child, rel, parent_id, src, edges)
            elif child.type in (
                "if_statement", "with_statement", "try_statement",
                "for_statement", "while_statement",
            ):
                for sub in child.children:
                    if sub.type == "block":
                        self._visit_block(
                            sub, rel, parent_qualname, parent_id,
                            enclosing_class_id, src, nodes, edges,
                        )

    def _handle_class(
        self,
        node: tree_sitter.Node,
        rel: str,
        parent_qualname: str,
        parent_id: str,
        src: bytes,
        nodes: list[Node],
        edges: list[Edge],
    ) -> None:
        name_node = node.child_by_field_name("name")
        if name_node is None:
            return
        name = node_text(name_node, src)
        qualname = f"{parent_qualname}.{name}" if parent_qualname else name
        class_id = make_node_id(NodeKind.CLASS, qualname, rel)

        sig = node_text(node, src).split("\n")[0].rstrip(":")

        body = node.child_by_field_name("body")
        docstring = _get_docstring(body, src) if body else None

        class_node = Node(
            id=class_id,
            kind=NodeKind.CLASS,
            name=name,
            qualname=qualname,
            file=rel,
            line_start=node.start_point[0] + 1,
            line_end=node.end_point[0] + 1,
            signature=sig,
            docstring=docstring,
            language="python",
            metadata={},
        )
        nodes.append(class_node)

        edges.append(Edge(
            src=class_id, dst=parent_id, kind=EdgeKind.DEFINED_IN,
            file=rel, line=node.start_point[0] + 1,
        ))

        arg_list = node.child_by_field_name("superclasses")
        if arg_list is None:
            for c in node.children:
                if c.type == "argument_list":
                    arg_list = c
                    break
        if arg_list is not None:
            for base in arg_list.children:
                if base.is_named and base.type in ("identifier", "attribute"):
                    base_name = node_text(base, src)
                    edges.append(Edge(
                        src=class_id,
                        dst=f"unresolved::{base_name}",
                        kind=EdgeKind.INHERITS,
                        file=rel,
                        line=node.start_point[0] + 1,
                        metadata={"target_name": base_name},
                    ))

        if body is not None:
            for child in body.children:
                if child.type == "function_definition":
                    self._handle_function(
                        child, rel, qualname, class_id,
                        NodeKind.METHOD, src, nodes, edges,
                    )
                elif child.type == "decorated_definition":
                    inner = None
                    for c in child.children:
                        if c.type in ("function_definition", "class_definition"):
                            inner = c
                            break
                    if inner is not None and inner.type == "function_definition":
                        self._handle_function(
                            inner, rel, qualname, class_id,
                            NodeKind.METHOD, src, nodes, edges,
                        )
                    elif inner is not None:
                        self._handle_class(
                            inner, rel, qualname, class_id, src, nodes, edges
                        )
                elif child.type == "class_definition":
                    self._handle_class(
                        child, rel, qualname, class_id, src, nodes, edges
                    )
                elif child.type == "import_statement":
                    self._handle_import(child, rel, class_id, src, edges)
                elif child.type == "import_from_statement":
                    self._handle_import_from(child, rel, class_id, src, edges)

    def _handle_function(
        self,
        node: tree_sitter.Node,
        rel: str,
        parent_qualname: str,
        parent_id: str,
        kind: NodeKind,
        src: bytes,
        nodes: list[Node],
        edges: list[Edge],
    ) -> None:
        name_node = node.child_by_field_name("name")
        if name_node is None:
            return
        name = node_text(name_node, src)
        qualname = f"{parent_qualname}.{name}" if parent_qualname else name
        func_id = make_node_id(kind, qualname, rel)

        params = node.child_by_field_name("parameters")
        sig = f"{name}{node_text(params, src)}" if params is not None else name

        body = node.child_by_field_name("body")
        docstring = _get_docstring(body, src) if body else None

        decorators = _get_function_decorators(node, src)

        func_node = Node(
            id=func_id,
            kind=kind,
            name=name,
            qualname=qualname,
            file=rel,
            line_start=node.start_point[0] + 1,
            line_end=node.end_point[0] + 1,
            signature=sig,
            docstring=docstring,
            language="python",
            metadata={"decorators": decorators},
        )
        nodes.append(func_node)

        edges.append(Edge(
            src=func_id, dst=parent_id, kind=EdgeKind.DEFINED_IN,
            file=rel, line=node.start_point[0] + 1,
        ))

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
        """Walk subtree collecting call expressions, stopping at nested defs."""
        stack: list[tree_sitter.Node] = list(node.children)
        while stack:
            child = stack.pop()
            if child.type == "call":
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
            if child.type not in ("class_definition", "function_definition"):
                stack.extend(child.children)

    def _handle_import(
        self,
        node: tree_sitter.Node,
        rel: str,
        parent_id: str,
        src: bytes,
        edges: list[Edge],
    ) -> None:
        for child in node.children:
            if child.type in ("dotted_name", "aliased_import"):
                if child.type == "aliased_import":
                    name_node = child.children[0] if child.children else child
                else:
                    name_node = child
                name = node_text(name_node, src)
                edges.append(Edge(
                    src=parent_id,
                    dst=f"unresolved::{name}",
                    kind=EdgeKind.IMPORTS,
                    file=rel,
                    line=node.start_point[0] + 1,
                    metadata={"target_name": name},
                ))

    def _handle_import_from(
        self,
        node: tree_sitter.Node,
        rel: str,
        parent_id: str,
        src: bytes,
        edges: list[Edge],
    ) -> None:
        # Locate the module portion (relative_import or dotted_name) and the
        # imported names that follow the `import` keyword.
        module_node: tree_sitter.Node | None = None
        seen_import_kw = False
        name_nodes: list[tree_sitter.Node] = []
        for child in node.children:
            if not seen_import_kw:
                if (
                    child.type in ("relative_import", "dotted_name")
                    and module_node is None
                ):
                    module_node = child
                elif child.type == "import":
                    seen_import_kw = True
            else:
                if child.type in ("dotted_name", "identifier"):
                    name_nodes.append(child)
                elif child.type == "aliased_import":
                    # `from m import X as Y` — bind original name X.
                    inner = next(
                        (
                            c for c in child.children
                            if c.type in ("dotted_name", "identifier")
                        ),
                        None,
                    )
                    if inner is not None:
                        name_nodes.append(inner)
                elif child.type == "wildcard_import":
                    # `from m import *` — no per-name edges to emit.
                    pass

        # Resolve module name. Handle relative imports by computing the
        # absolute package qualname from the importing file's location.
        module_name = self._resolve_from_module(module_node, rel, src)

        # If there are no imported names (e.g. parser fallback), keep the
        # module-level edge so we don't lose the import entirely. When we
        # do have per-name edges, the per-name edges carry the binding info
        # the resolver needs and the module-level edge would be redundant
        # noise.
        if module_name and not name_nodes:
            edges.append(Edge(
                src=parent_id,
                dst=f"unresolved::{module_name}",
                kind=EdgeKind.IMPORTS,
                file=rel,
                line=node.start_point[0] + 1,
                metadata={"target_name": module_name},
            ))

        # Emit one IMPORTS edge per imported name, with imported_name in the
        # metadata so the resolver can bind alias -> full qualname.
        for nn in name_nodes:
            imported = node_text(nn, src)
            if not imported:
                continue
            full = (
                f"{module_name}.{imported}" if module_name else imported
            )
            edges.append(Edge(
                src=parent_id,
                dst=f"unresolved::{full}",
                kind=EdgeKind.IMPORTS,
                file=rel,
                line=node.start_point[0] + 1,
                metadata={
                    "target_name": full,
                    "imported_name": imported,
                },
            ))

    def _resolve_from_module(
        self,
        module_node: tree_sitter.Node | None,
        rel: str,
        src: bytes,
    ) -> str:
        """Return the absolute module qualname for a `from X import ...`.

        For relative imports (`from . import x`, `from ..pkg import x`),
        count the leading dots and walk up the importing file's package
        path that many levels, then append the relative module name.
        """
        if module_node is None:
            return ""
        if module_node.type != "relative_import":
            return node_text(module_node, src)

        # Count leading dots and find the trailing dotted_name (if any).
        dots = 0
        rel_module = ""
        for child in module_node.children:
            if child.type == "import_prefix":
                dots = sum(1 for c in child.children if c.type == ".")
            elif child.type == "dotted_name":
                rel_module = node_text(child, src)

        # Importing-file qualname (without the file's own basename).
        file_qual = _file_to_qualname(rel)
        pkg_parts = file_qual.split(".") if file_qual else []
        # Drop the file's own module name to get the containing package.
        if pkg_parts:
            pkg_parts = pkg_parts[:-1]
        # Walk up `dots - 1` further levels (one dot = current package).
        if dots > 1:
            cut = dots - 1
            pkg_parts = pkg_parts[:-cut] if cut <= len(pkg_parts) else []

        parts = pkg_parts + ([rel_module] if rel_module else [])
        return ".".join(p for p in parts if p)
