"""Go (tree-sitter) extractor for codegraph.

Emits the same node/edge shape as :mod:`codegraph.parsers.python` so the
post-build resolver in :mod:`codegraph.resolve.calls` can wire up cross-file
references uniformly. Tree-sitter Go grammar is loaded lazily via
``tree-sitter-go``.

Node kinds emitted
------------------
- ``MODULE``  — one per ``.go`` file. Qualname is the package name from
  ``package X``, fallback to file path slug. Files in the same package
  intentionally share a qualname so call-site resolution finds them.
- ``CLASS``   — Go ``type X struct {...}`` and ``type X interface {...}``.
  (Not really classes, but the post-build resolver treats CLASS as "named
  type" and that's what struct/interface declarations are.)
- ``FUNCTION``— top-level ``func Foo(...) {...}``.
- ``METHOD``  — ``func (r *Recv) Foo(...) {...}``. Qualname is
  ``module.ReceiverType.Foo``.

Edge kinds emitted
------------------
- ``DEFINED_IN`` — every function/method/type → its parent module (or
  receiver type, in the case of methods).
- ``IMPORTS``   — module → ``unresolved::<package-path>`` per import.
- ``CALLS``     — function/method body → ``unresolved::<target>`` per
  call site. Targets are emitted as the bare identifier (e.g. ``Foo``) or
  dotted selector (e.g. ``pkg.Foo`` / ``r.Foo``); the resolver narrows.
- ``INHERITS``  — struct → unresolved::EmbeddedType for each embedded
  type field. (Go composition is the closest analog to inheritance.)

Limitations (v1)
----------------
- Generic type parameters are parsed but stored only as text in metadata;
  the qualname doesn't include them.
- Interface-satisfaction (does ``*Foo`` implement ``Bar``?) is not detected
  here — that needs a whole-package pass. The resolver layer is where this
  should land, not the parser.
- ``init()`` functions and ``main()`` get no special treatment yet.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import tree_sitter

from codegraph.graph.schema import Edge, EdgeKind, Node, NodeKind, make_node_id
from codegraph.parsers.base import (
    ExtractorBase,
    load_parser,
    node_text,
    register_extractor,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _file_to_module_qualname_fallback(rel: str) -> str:
    """Convert ``cmd/foo/bar.go`` → ``cmd.foo.bar`` when no ``package X`` is found.

    Used only when the file is unparseable enough that we can't read the
    package clause (shouldn't happen for valid Go, but defensive).
    """
    stem = rel.rsplit(".", 1)[0]
    return stem.replace("/", ".") or "main"


def _is_test_file(rel: str) -> bool:
    """Go convention: ``*_test.go`` is a test file."""
    name = rel.rsplit("/", 1)[-1]
    return name.endswith("_test.go")


def _named_children(ts_node: tree_sitter.Node) -> list[tree_sitter.Node]:
    return [c for c in ts_node.children if c.is_named]


def _find_child(ts_node: tree_sitter.Node, kind: str) -> tree_sitter.Node | None:
    for c in ts_node.children:
        if c.type == kind:
            return c
    return None


def _find_named_descendant(
    ts_node: tree_sitter.Node, kinds: set[str]
) -> tree_sitter.Node | None:
    """Depth-first search for the first descendant whose type is in *kinds*."""
    stack: list[tree_sitter.Node] = list(ts_node.children)
    while stack:
        cur = stack.pop()
        if cur.type in kinds:
            return cur
        stack.extend(cur.children)
    return None


def _extract_receiver_type(
    method_node: tree_sitter.Node, src: bytes
) -> tuple[str | None, bool]:
    """Pull the receiver type name + pointer-ness out of a method_declaration.

    Returns ``(type_name, is_pointer)`` or ``(None, False)`` if not parseable.
    """
    # method_declaration → first child is the receiver parameter_list
    pl = _find_child(method_node, "parameter_list")
    if pl is None:
        return None, False
    # Inside the receiver param list: parameter_declaration → type
    pd = _find_child(pl, "parameter_declaration")
    if pd is None:
        return None, False
    type_node = pd.child_by_field_name("type")
    if type_node is None:
        # Some grammars: type lives as the last named child
        named = _named_children(pd)
        type_node = named[-1] if named else None
    if type_node is None:
        return None, False
    is_pointer = False
    if type_node.type == "pointer_type":
        is_pointer = True
        # tree-sitter-go doesn't expose the pointed-to type as a named field;
        # walk children for the first named ``type_identifier`` (also handles
        # qualified types like ``pkg.Foo`` via ``qualified_type``).
        inner: tree_sitter.Node | None = None
        for c in type_node.children:
            if c.type in ("type_identifier", "qualified_type"):
                inner = c
                break
        if inner is not None:
            type_node = inner
    return node_text(type_node, src).strip(), is_pointer


def _params_metadata(
    params_node: tree_sitter.Node | None, src: bytes
) -> list[dict[str, Any]]:
    """Extract parameters as ``[{"name": "...", "type": "..."}]``."""
    if params_node is None:
        return []
    out: list[dict[str, Any]] = []
    for child in params_node.children:
        if child.type != "parameter_declaration":
            continue
        type_node = child.child_by_field_name("type")
        type_str = node_text(type_node, src).strip() if type_node else None
        names: list[str] = []
        for sub in child.children:
            if sub.type == "identifier":
                names.append(node_text(sub, src))
        if not names:
            # Anonymous parameter (just a type, e.g. `func f(int)`)
            out.append({"name": "", "type": type_str})
        else:
            for n in names:
                out.append({"name": n, "type": type_str})
    return out


def _signature_text(decl: tree_sitter.Node, src: bytes) -> str:
    """Best-effort: ``func Name(...) result``. Skips the body."""
    body = _find_child(decl, "block")
    end = body.start_byte if body else decl.end_byte
    return src[decl.start_byte:end].decode("utf-8", errors="replace").strip()


# ---------------------------------------------------------------------------
# Main extractor
# ---------------------------------------------------------------------------


@register_extractor
class GoExtractor(ExtractorBase):
    language = "go"
    extensions = (".go",)

    def parse_file(
        self, path: Path, repo_root: Path
    ) -> tuple[list[Node], list[Edge]]:
        try:
            src = path.read_bytes()
        except OSError:
            return [], []
        rel = path.relative_to(repo_root).as_posix()
        parser = load_parser("go")
        tree = parser.parse(src)
        root = tree.root_node

        nodes: list[Node] = []
        edges: list[Edge] = []

        # 1. Module node — qualname is the package name when we can find it.
        package_name = self._read_package_name(root, src)
        module_qualname = package_name or _file_to_module_qualname_fallback(rel)
        module_kind = NodeKind.TEST if _is_test_file(rel) else NodeKind.MODULE
        module_id = make_node_id(module_kind, module_qualname, rel)
        nodes.append(
            Node(
                id=module_id,
                kind=module_kind,
                name=path.stem,
                qualname=module_qualname,
                file=rel,
                line_start=1,
                line_end=root.end_point[0] + 1,
                language="go",
                metadata={"package": package_name} if package_name else {},
            )
        )

        # 2. Walk top-level declarations.
        for child in _named_children(root):
            if child.type == "import_declaration":
                self._handle_imports(child, rel, module_id, src, edges)
            elif child.type == "function_declaration":
                self._handle_function(
                    child, rel, module_qualname, module_id, src, nodes, edges
                )
            elif child.type == "method_declaration":
                self._handle_method(
                    child, rel, module_qualname, module_id, src, nodes, edges
                )
            elif child.type == "type_declaration":
                self._handle_type_decl(
                    child, rel, module_qualname, module_id, src, nodes, edges
                )

        return nodes, edges

    # -----------------------------------------------------------------------
    # Top-level structure
    # -----------------------------------------------------------------------

    def _read_package_name(
        self, root: tree_sitter.Node, src: bytes
    ) -> str | None:
        for child in root.children:
            if child.type != "package_clause":
                continue
            ident = _find_child(child, "package_identifier") or _find_child(
                child, "identifier"
            )
            if ident is not None:
                return node_text(ident, src)
        return None

    def _handle_imports(
        self,
        decl: tree_sitter.Node,
        rel: str,
        module_id: str,
        src: bytes,
        edges: list[Edge],
    ) -> None:
        """Emit one ``IMPORTS`` edge per imported package path.

        Handles three forms:
          - ``import "fmt"``                         (single spec)
          - ``import ( "fmt" "os" )``                (grouped specs)
          - ``import foo "github.com/.../foo"``      (named import)
          - ``import _ "github.com/.../driver"``     (blank import)
        """
        for spec in _named_children(decl):
            specs: list[tree_sitter.Node] = []
            if spec.type == "import_spec":
                specs.append(spec)
            elif spec.type == "import_spec_list":
                specs.extend(c for c in _named_children(spec) if c.type == "import_spec")
            for s in specs:
                path_node = _find_child(s, "interpreted_string_literal")
                if path_node is None:
                    path_node = _find_child(s, "raw_string_literal")
                if path_node is None:
                    continue
                pkg_path = node_text(path_node, src).strip("`").strip('"')
                if not pkg_path:
                    continue
                alias_node = _find_child(s, "package_identifier") or _find_child(
                    s, "identifier"
                )
                alias = node_text(alias_node, src) if alias_node else None
                metadata: dict[str, Any] = {"package_path": pkg_path}
                if alias and alias != pkg_path.rsplit("/", 1)[-1]:
                    metadata["alias"] = alias
                edges.append(
                    Edge(
                        src=module_id,
                        dst=f"unresolved::{pkg_path}",
                        kind=EdgeKind.IMPORTS,
                        file=rel,
                        line=s.start_point[0] + 1,
                        metadata=metadata,
                    )
                )

    # -----------------------------------------------------------------------
    # Functions, methods, types
    # -----------------------------------------------------------------------

    def _handle_function(
        self,
        decl: tree_sitter.Node,
        rel: str,
        parent_qualname: str,
        parent_id: str,
        src: bytes,
        nodes: list[Node],
        edges: list[Edge],
    ) -> None:
        name_node = decl.child_by_field_name("name")
        if name_node is None:
            return
        name = node_text(name_node, src)
        qualname = f"{parent_qualname}.{name}"
        fn_id = make_node_id(NodeKind.FUNCTION, qualname, rel)
        params_meta = _params_metadata(decl.child_by_field_name("parameters"), src)
        nodes.append(
            Node(
                id=fn_id,
                kind=NodeKind.FUNCTION,
                name=name,
                qualname=qualname,
                file=rel,
                line_start=decl.start_point[0] + 1,
                line_end=decl.end_point[0] + 1,
                signature=_signature_text(decl, src),
                language="go",
                metadata={"params": params_meta},
            )
        )
        edges.append(
            Edge(
                src=fn_id,
                dst=parent_id,
                kind=EdgeKind.DEFINED_IN,
                file=rel,
                line=decl.start_point[0] + 1,
            )
        )
        body = _find_child(decl, "block")
        if body is not None:
            self._collect_calls(body, rel, fn_id, src, edges)

    def _handle_method(
        self,
        decl: tree_sitter.Node,
        rel: str,
        parent_qualname: str,
        parent_id: str,
        src: bytes,
        nodes: list[Node],
        edges: list[Edge],
    ) -> None:
        name_node = decl.child_by_field_name("name")
        if name_node is None:
            return
        name = node_text(name_node, src)
        recv_type, is_pointer = _extract_receiver_type(decl, src)
        # Qualname: prefer module.RecvType.Name so the resolver can stitch
        # the method to its type. Fallback to module.Name when receiver isn't
        # parseable.
        if recv_type:
            qualname = f"{parent_qualname}.{recv_type}.{name}"
            recv_type_qualname = f"{parent_qualname}.{recv_type}"
        else:
            qualname = f"{parent_qualname}.{name}"
            recv_type_qualname = None
        method_id = make_node_id(NodeKind.METHOD, qualname, rel)
        params_meta = _params_metadata(decl.child_by_field_name("parameters"), src)
        nodes.append(
            Node(
                id=method_id,
                kind=NodeKind.METHOD,
                name=name,
                qualname=qualname,
                file=rel,
                line_start=decl.start_point[0] + 1,
                line_end=decl.end_point[0] + 1,
                signature=_signature_text(decl, src),
                language="go",
                metadata={
                    "params": params_meta,
                    "receiver": recv_type,
                    "receiver_pointer": is_pointer,
                },
            )
        )
        # Method DEFINED_IN points at the receiver type if we know it, else module.
        # The resolver expects to find the dst by node ID; for the receiver case
        # we emit an unresolved:: edge so the resolver can match by qualname.
        if recv_type_qualname:
            edges.append(
                Edge(
                    src=method_id,
                    dst=f"unresolved::{recv_type_qualname}",
                    kind=EdgeKind.DEFINED_IN,
                    file=rel,
                    line=decl.start_point[0] + 1,
                )
            )
        else:
            edges.append(
                Edge(
                    src=method_id,
                    dst=parent_id,
                    kind=EdgeKind.DEFINED_IN,
                    file=rel,
                    line=decl.start_point[0] + 1,
                )
            )
        body = _find_child(decl, "block")
        if body is not None:
            self._collect_calls(body, rel, method_id, src, edges)

    def _handle_type_decl(
        self,
        decl: tree_sitter.Node,
        rel: str,
        parent_qualname: str,
        parent_id: str,
        src: bytes,
        nodes: list[Node],
        edges: list[Edge],
    ) -> None:
        """Emit a CLASS node per ``type Foo ...`` spec inside the declaration."""
        for spec in _named_children(decl):
            if spec.type != "type_spec":
                continue
            name_node = spec.child_by_field_name("name") or _find_child(
                spec, "type_identifier"
            )
            if name_node is None:
                continue
            name = node_text(name_node, src)
            qualname = f"{parent_qualname}.{name}"
            type_id = make_node_id(NodeKind.CLASS, qualname, rel)
            inner = spec.child_by_field_name("type")
            inner_kind = inner.type if inner is not None else "unknown"
            metadata: dict[str, Any] = {"type_kind": inner_kind}
            nodes.append(
                Node(
                    id=type_id,
                    kind=NodeKind.CLASS,
                    name=name,
                    qualname=qualname,
                    file=rel,
                    line_start=spec.start_point[0] + 1,
                    line_end=spec.end_point[0] + 1,
                    language="go",
                    metadata=metadata,
                )
            )
            edges.append(
                Edge(
                    src=type_id,
                    dst=parent_id,
                    kind=EdgeKind.DEFINED_IN,
                    file=rel,
                    line=spec.start_point[0] + 1,
                )
            )
            # Embedded fields → INHERITS (Go's composition idiom).
            if inner is not None and inner.type == "struct_type":
                self._collect_embedded_fields(inner, rel, type_id, src, edges)

    def _collect_embedded_fields(
        self,
        struct_node: tree_sitter.Node,
        rel: str,
        type_id: str,
        src: bytes,
        edges: list[Edge],
    ) -> None:
        """An embedded field is a ``field_declaration`` with NO field name —
        only a type. Treat it as composition / pseudo-inheritance.
        """
        field_list = _find_child(struct_node, "field_declaration_list")
        if field_list is None:
            return
        for field in _named_children(field_list):
            if field.type != "field_declaration":
                continue
            name_node = field.child_by_field_name("name")
            if name_node is not None:
                continue  # explicit-name field, not embedded
            type_node = field.child_by_field_name("type")
            if type_node is None:
                continue
            embedded = node_text(type_node, src).lstrip("*").strip()
            if not embedded:
                continue
            edges.append(
                Edge(
                    src=type_id,
                    dst=f"unresolved::{embedded}",
                    kind=EdgeKind.INHERITS,
                    file=rel,
                    line=field.start_point[0] + 1,
                    metadata={"embedded": True},
                )
            )

    # -----------------------------------------------------------------------
    # Call sites — walk the body, emit CALLS edges per call_expression.
    # -----------------------------------------------------------------------

    def _collect_calls(
        self,
        body: tree_sitter.Node,
        rel: str,
        scope_id: str,
        src: bytes,
        edges: list[Edge],
    ) -> None:
        """Stack-based DFS over the function body, emitting CALLS edges per
        ``call_expression``. Stops descending into nested function literals so
        their calls are attributed to the enclosing scope (mirrors python.py).
        """
        stack: list[tree_sitter.Node] = list(body.children)
        while stack:
            cur = stack.pop()
            if cur.type == "call_expression":
                target = self._call_target_text(cur, src)
                if target:
                    edges.append(
                        Edge(
                            src=scope_id,
                            dst=f"unresolved::{target}",
                            kind=EdgeKind.CALLS,
                            file=rel,
                            line=cur.start_point[0] + 1,
                            metadata={"target_name": target},
                        )
                    )
            # Stop at nested function literals — their calls belong to them.
            if cur.type in ("func_literal", "function_declaration", "method_declaration"):
                continue
            stack.extend(cur.children)

    def _call_target_text(
        self, call: tree_sitter.Node, src: bytes
    ) -> str | None:
        """Best-effort textual rendering of the call target.

        ``Foo()``         → ``Foo``
        ``pkg.Foo()``     → ``pkg.Foo``
        ``r.Method()``    → ``r.Method``
        ``r.M().X()``     → ``X``  (chained — keep the rightmost selector)
        """
        fn = call.child_by_field_name("function")
        if fn is None:
            return None
        if fn.type == "identifier":
            return node_text(fn, src)
        if fn.type == "selector_expression":
            operand = fn.child_by_field_name("operand")
            field = fn.child_by_field_name("field")
            if field is None:
                return None
            if operand is not None and operand.type in ("identifier", "selector_expression"):
                # Simple package or receiver reference — keep the full dotted name.
                return f"{node_text(operand, src)}.{node_text(field, src)}"
            # Chained / complex operand — fall back to the rightmost identifier
            # so the resolver can at least try a tail match.
            return node_text(field, src)
        # Type conversions, function literals etc. — skip
        return None
