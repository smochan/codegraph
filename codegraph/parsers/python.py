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


def _collect_class_attr_types(
    body: tree_sitter.Node, src: bytes
) -> dict[str, str]:
    """Return ``{attr_name: type_qualname}`` for class-level annotations.

    Tree-sitter wraps each ``name: Type`` line as
    ``expression_statement -> assignment -> identifier ":" type -> ...``.
    We extract simple identifier and dotted-attribute types only; complex
    generics (``list[Foo]``) and string forward refs are ignored — those
    require type-system reasoning beyond the current resolver budget.
    """
    out: dict[str, str] = {}
    for stmt in body.children:
        if stmt.type != "expression_statement":
            continue
        for assignment in stmt.children:
            if assignment.type != "assignment":
                continue
            name_node: tree_sitter.Node | None = None
            type_node: tree_sitter.Node | None = None
            for c in assignment.children:
                if c.type == "identifier" and name_node is None:
                    name_node = c
                elif c.type == "type":
                    type_node = c
            if name_node is None or type_node is None:
                continue
            # Inner of `type` is usually a single identifier or attribute.
            inner: tree_sitter.Node | None = None
            for c in type_node.children:
                if c.type in ("identifier", "attribute"):
                    inner = c
                    break
            if inner is None:
                continue
            attr_name = node_text(name_node, src)
            type_text = node_text(inner, src)
            if attr_name and type_text:
                out[attr_name] = type_text
    return out


# --- Argument expression simplification ---------------------------------
#
# Per DF0 spec: "simple" arg expressions (literals, identifiers, attributes,
# subscripts) are captured verbatim; anything else collapses to "<expr>".
_SIMPLE_ARG_TYPES: frozenset[str] = frozenset({
    "identifier", "string", "integer", "float",
    "true", "false", "none",
    "attribute", "subscript",
})


def _simplify_arg(node: tree_sitter.Node, src: bytes) -> str:
    """Return arg text if the AST node is a simple form, else ``"<expr>"``."""
    if node.type in _SIMPLE_ARG_TYPES:
        return node_text(node, src)
    return "<expr>"


def _extract_params(
    params_node: tree_sitter.Node,
    src: bytes,
    *,
    skip_self_or_cls: bool,
) -> list[dict[str, str | None]]:
    """Walk a ``parameters`` AST block and return DF0 param descriptors.

    Skip the first parameter when ``skip_self_or_cls`` is True and that
    first parameter is named ``self`` or ``cls``. Variadic forms are
    captured with ``*`` / ``**`` prefixes on the name.
    """
    out: list[dict[str, str | None]] = []
    first_seen = False
    for child in params_node.children:
        if not child.is_named:
            continue
        descriptor: dict[str, str | None] | None = None
        if child.type == "identifier":
            descriptor = {
                "name": node_text(child, src),
                "type": None,
                "default": None,
            }
        elif child.type == "typed_parameter":
            name_n = next(
                (c for c in child.children if c.type == "identifier"), None
            )
            type_n = next(
                (c for c in child.children if c.type == "type"), None
            )
            if name_n is not None:
                descriptor = {
                    "name": node_text(name_n, src),
                    "type": node_text(type_n, src) if type_n else None,
                    "default": None,
                }
        elif child.type == "default_parameter":
            name_n = child.child_by_field_name("name")
            value_n = child.child_by_field_name("value")
            if name_n is not None:
                descriptor = {
                    "name": node_text(name_n, src),
                    "type": None,
                    "default": node_text(value_n, src) if value_n else None,
                }
        elif child.type == "typed_default_parameter":
            name_n = child.child_by_field_name("name")
            type_n = child.child_by_field_name("type")
            value_n = child.child_by_field_name("value")
            if name_n is not None:
                descriptor = {
                    "name": node_text(name_n, src),
                    "type": node_text(type_n, src) if type_n else None,
                    "default": node_text(value_n, src) if value_n else None,
                }
        elif child.type == "list_splat_pattern":
            inner = next(
                (c for c in child.children if c.type == "identifier"), None
            )
            if inner is not None:
                descriptor = {
                    "name": f"*{node_text(inner, src)}",
                    "type": None,
                    "default": None,
                }
        elif child.type == "dictionary_splat_pattern":
            inner = next(
                (c for c in child.children if c.type == "identifier"), None
            )
            if inner is not None:
                descriptor = {
                    "name": f"**{node_text(inner, src)}",
                    "type": None,
                    "default": None,
                }
        if descriptor is None:
            continue
        if (
            skip_self_or_cls
            and not first_seen
            and descriptor["name"] in ("self", "cls")
        ):
            first_seen = True
            continue
        first_seen = True
        out.append(descriptor)
    return out


def _extract_call_args(
    arg_list: tree_sitter.Node, src: bytes
) -> tuple[list[str], dict[str, str]]:
    """Return ``(args, kwargs)`` for a ``call.argument_list`` AST node.

    Follows the DF0 capture rules: positional args are simplified via
    ``_simplify_arg``; keyword args become ``kwargs[name] = simplified``;
    ``*spread`` becomes ``"*name"`` in args; ``**spread`` becomes
    ``kwargs["**"] = name``.
    """
    args: list[str] = []
    kwargs: dict[str, str] = {}
    for child in arg_list.children:
        if not child.is_named:
            continue
        if child.type == "keyword_argument":
            name_n = child.child_by_field_name("name")
            value_n = child.child_by_field_name("value")
            if name_n is not None and value_n is not None:
                kwargs[node_text(name_n, src)] = _simplify_arg(value_n, src)
        elif child.type == "list_splat":
            inner = next(
                (c for c in child.children if c.is_named), None
            )
            if inner is not None:
                args.append(f"*{node_text(inner, src)}")
            else:
                args.append("<expr>")
        elif child.type == "dictionary_splat":
            inner = next(
                (c for c in child.children if c.is_named), None
            )
            if inner is not None:
                kwargs["**"] = node_text(inner, src)
        else:
            args.append(_simplify_arg(child, src))
    return args, kwargs


# --- DF1: HTTP route + SQLAlchemy detection ---------------------------
#
# Patterns are regex-based on the raw decorator / call text. Tree-sitter
# gives us reliable syntactic boundaries; we lean on regex for the inner
# semantic shape (HTTP method names, model arguments) since the surface
# vocabulary is small and well-known.

# Recognised HTTP verbs / route helpers across FastAPI, Flask, aiohttp.
_HTTP_VERBS: tuple[str, ...] = (
    "get", "post", "put", "delete", "patch",
    "head", "options", "trace", "websocket",
)

# Decorator forms:
#   @<router>.<verb>("/path", ...)
#   @<router>.<verb>('/path', ...)
# router is any identifier (app, router, blueprint, bp, ...).
_ROUTE_VERB_RE = re.compile(
    r"@\s*(?P<router>[\w.]+)\.(?P<verb>"
    + "|".join(_HTTP_VERBS)
    + r")\s*\(\s*['\"](?P<path>[^'\"]+)['\"]"
)
# @<router>.route("/path", methods=[...]) — Flask shape.
_ROUTE_GENERIC_RE = re.compile(
    r"@\s*(?P<router>[\w.]+)\.route\s*\(\s*['\"](?P<path>[^'\"]+)['\"]"
)
_METHODS_KW_RE = re.compile(
    r"methods\s*=\s*\[(?P<methods>[^\]]*)\]"
)
_METHOD_TOKEN_RE = re.compile(r"['\"]([A-Za-z]+)['\"]")

# FastAPI-style routers vs Flask app/blueprint heuristic for `framework`.
_FASTAPI_ROUTER_TOKENS: frozenset[str] = frozenset({
    "router", "api_router", "apirouter",
})
_FLASK_ROUTER_TOKENS: frozenset[str] = frozenset({
    "blueprint", "bp", "blueprints",
})


def _classify_framework(router_name: str, has_methods_kw: bool) -> str:
    """Best-effort framework guess for ROUTE edge metadata.

    Heuristics:
    * ``methods=[...]`` keyword is Flask-shaped; FastAPI's per-verb
      decorators don't accept it.
    * Names containing ``router`` lean FastAPI; ``blueprint``/``bp``
      lean Flask. Fallback is ``fastapi`` since it is by far the most
      common modern Python web framework.
    """
    head = router_name.rsplit(".", 1)[-1].lower()
    if has_methods_kw:
        return "flask"
    if head in _FLASK_ROUTER_TOKENS:
        return "flask"
    if head in _FASTAPI_ROUTER_TOKENS:
        return "fastapi"
    return "fastapi"


def _extract_route_specs(
    decorators: list[str],
) -> list[dict[str, str]]:
    """Return one dict per HTTP route described by the decorators.

    Flask's ``@app.route("/x", methods=["GET", "POST"])`` produces ONE
    dict per method (so caller emits one ROUTE edge per method).
    FastAPI's ``@app.get("/x")`` produces a single dict.

    Each dict has keys: ``method`` (uppercase), ``path``, ``framework``,
    ``router`` (raw router-variable text).
    """
    out: list[dict[str, str]] = []
    for raw in decorators:
        text = raw.strip()
        # @<router>.route(...) — handle FIRST so methods kw is honored,
        # otherwise the verb regex would never match (no verb in decl).
        m = _ROUTE_GENERIC_RE.search(text)
        if m:
            router = m.group("router")
            path = m.group("path")
            framework = _classify_framework(router, has_methods_kw=True)
            mm = _METHODS_KW_RE.search(text)
            if mm:
                methods = [
                    tok.upper()
                    for tok in _METHOD_TOKEN_RE.findall(mm.group("methods"))
                ]
            else:
                # Default Flask method when methods= is absent.
                methods = ["GET"]
            for method in methods:
                out.append({
                    "method": method,
                    "path": path,
                    "framework": framework,
                    "router": router,
                })
            continue
        # @<router>.<verb>(path, ...)
        m2 = _ROUTE_VERB_RE.search(text)
        if m2:
            router = m2.group("router")
            verb = m2.group("verb")
            path = m2.group("path")
            framework = _classify_framework(router, has_methods_kw=False)
            out.append({
                "method": verb.upper(),
                "path": path,
                "framework": framework,
                "router": router,
            })
    return out


# --- SQLAlchemy detection ----------------------------------------------
#
# We detect data-access patterns at parse time and emit READS_FROM /
# WRITES_TO edges with ``dst="unresolved::<ModelName>"``. The post-build
# resolver rewrites these to real CLASS node ids when the model is in
# repo; any that remain unresolved are dropped (per DF1 spec).

# Outer verbs we recognise on session/db/conn.
_SQL_READ_OUTER: frozenset[str] = frozenset({"query", "get", "scalar", "scalars"})
_SQL_WRITE_OUTER: frozenset[str] = frozenset({"add", "add_all", "delete", "merge"})
# Inner verbs in session.execute(<inner>(Model)).
_SQL_READ_INNER: frozenset[str] = frozenset({"select"})
_SQL_WRITE_INNER: frozenset[str] = frozenset({"insert", "update", "delete"})

# `session`, `db.session`, `db`, `conn`, `cursor`, ... — left-most token
# of a chain that suggests an ORM/connection root. We accept any
# identifier and rely on ``execute``/``query``/``add``/etc. as the verb
# trigger, but record the chain's last identifier in metadata.
_SESSION_HEAD_TOKENS: frozenset[str] = frozenset({
    "session", "db", "conn", "connection", "cursor",
})


def _strip_call_suffix(name: str) -> str:
    """Drop `()` and trailing chained calls — `Foo().bar` -> `Foo.bar`."""
    out: list[str] = []
    depth = 0
    for ch in name:
        if ch == "(":
            depth += 1
            continue
        if ch == ")":
            if depth > 0:
                depth -= 1
            continue
        if depth == 0:
            out.append(ch)
    return "".join(out).strip().rstrip(".")


def _is_session_chain(target: str) -> bool:
    """Return True if the dotted chain's left-most segment looks like a
    session/db handle (``session.query``, ``db.session.query``, ...)."""
    if not target:
        return False
    head = target.split(".", 1)[0].lower()
    return head in _SESSION_HEAD_TOKENS


def _unwrap_to_root_call(node: tree_sitter.Node) -> tree_sitter.Node | None:
    """Follow ``call.function -> attribute.object`` chains down to the
    leftmost ``call`` node.

    Used for ``select(Model).where(...).order_by(...)`` style chains so we
    extract ``select(Model)``'s argument, not the outer chained call's.
    """
    cur: tree_sitter.Node | None = node
    while cur is not None and cur.type == "call":
        func_child = cur.child_by_field_name("function")
        # If function is itself an attribute whose object is a call, the
        # inner call is the "root"; descend.
        if (
            func_child is not None
            and func_child.type == "attribute"
        ):
            obj = func_child.child_by_field_name("object")
            if obj is not None and obj.type == "call":
                cur = obj
                continue
        break
    return cur


def _model_name_from_call_arg(arg_text: str) -> str | None:
    """Extract a Model name from a call-argument expression.

    Handles:
    * ``User`` — bare identifier
    * ``User(...)`` — constructor call (returns ``User``)
    * ``[User(...), Other()]`` — list with a Model constructor (returns
      ``User``, the first model)
    * ``some_chain.User`` — last segment
    """
    if not arg_text:
        return None
    text = arg_text.strip()
    if text.startswith("[") and text.endswith("]"):
        # ``add_all([User(...), ...])`` — pick the first PascalCase token.
        inner = text[1:-1]
        tokens: list[str] = re.findall(r"[A-Za-z_][A-Za-z0-9_]*", inner)
        for tok in tokens:
            if tok and tok[0].isupper():
                return tok
        return None
    # Drop call args / parens.
    no_parens = _strip_call_suffix(text)
    # Last identifier segment after dotting.
    leaf = no_parens.rsplit(".", 1)[-1]
    if not leaf or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", leaf):
        return None
    if not leaf[0].isupper():
        return None
    return leaf


def _get_function_decorators(func_node: tree_sitter.Node, src: bytes) -> list[str]:
    """Collect decorator strings for a function/class definition.

    Tree-sitter wraps decorated definitions in a ``decorated_definition``
    parent whose siblings are the ``decorator`` nodes; the actual
    ``function_definition``/``class_definition`` itself has no decorator
    children. We therefore look at the parent when needed.
    """
    decs: list[str] = []
    container: tree_sitter.Node | None = func_node
    if (
        func_node.parent is not None
        and func_node.parent.type == "decorated_definition"
    ):
        container = func_node.parent
    if container is None:
        return decs
    for child in container.children:
        if child.type == "decorator":
            decs.append(node_text(child, src))
    return decs


# --- Entry-point decorator catalog ---------------------------------------
#
# Decorator-prefix patterns (matched as substring of the raw "@..." text).
# Order is irrelevant; first match wins. Patterns starting with ``@`` match
# only at the start of the decorator string, while patterns without a
# leading ``@`` are matched as a contained substring (so ``@<name>.command``
# style patterns require explicit suffixes).
_ENTRYPOINT_DECORATOR_SUFFIXES: tuple[str, ...] = (
    # Typer / Click — bound to any local Typer/Click instance.
    ".command", ".callback", ".group",
    # FastAPI / Flask / aiohttp — HTTP and websocket route decorators.
    ".get", ".post", ".put", ".delete", ".patch", ".head", ".options",
    ".trace", ".websocket", ".route", ".on_event", ".middleware",
    ".before_request", ".after_request", ".teardown_request",
    ".errorhandler",
    # Celery.
    ".task",
    # SQLAlchemy.
    ".listens_for",
    # MCP protocol server (anthropic mcp-python-sdk and similar).
    ".list_tools", ".call_tool", ".list_resources", ".read_resource",
    ".list_prompts", ".get_prompt",
)

# Decorator names matched anywhere in the raw decorator text (covers bare
# ``@shared_task`` as well as ``@app.shared_task`` and ``@pytest.fixture``).
_ENTRYPOINT_DECORATOR_CONTAINS: tuple[str, ...] = (
    "shared_task",
    "pytest.fixture",
    "pytest.mark",
    "abstractmethod",
    "abc.abstractmethod",
    "admin.register",
    "receiver",
    "login_required",
    "permission_required",
    "event.listens_for",
    # Local registry decorators commonly used in this codebase / MCP servers.
    "_register",
)


def _is_entry_point(
    decorators: list[str],
    name: str,
    *,
    extra_decorator_patterns: tuple[str, ...] = (),
) -> bool:
    """Return True if any decorator matches a known entry-point pattern.

    ``name`` is currently unused but kept for forward compatibility with
    name-glob configuration in DeadCodeConfig.
    """
    if not decorators:
        return False
    for raw in decorators:
        text = raw.strip()
        # Drop the leading '@' for substring matching, but keep the raw
        # form for prefix matching.
        body = text[1:] if text.startswith("@") else text
        for suffix in _ENTRYPOINT_DECORATOR_SUFFIXES:
            if suffix in body:
                return True
        for needle in _ENTRYPOINT_DECORATOR_CONTAINS:
            if needle in body:
                return True
        for pattern in extra_decorator_patterns:
            stripped = pattern.lstrip("@").strip()
            if stripped and stripped in body:
                return True
    return False


@register_extractor
class PythonExtractor(ExtractorBase):
    language = "python"
    extensions = (".py",)

    # Optional user-supplied decorator patterns (set by GraphBuilder before
    # parsing). Matched as substring of the raw decorator text via
    # ``_is_entry_point``.
    extra_entry_point_decorators: tuple[str, ...] = ()

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
        # Module-level call expressions (e.g. `Widget("a")` at top level)
        # also produce CALLS edges attributed to the module so the resolver
        # can link them to in-repo classes/functions defined in the same
        # file. We deliberately stop traversal at any function/class def so
        # we don't double-count their inner calls.
        self._collect_calls(root, rel, module_id, src, edges)
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

        decorators = _get_function_decorators(node, src)
        cls_metadata: dict[str, object] = {}
        if decorators:
            cls_metadata["decorators"] = decorators
        if _is_entry_point(
            decorators,
            name,
            extra_decorator_patterns=self.extra_entry_point_decorators,
        ):
            cls_metadata["entry_point"] = True

        body_for_attrs = node.child_by_field_name("body")
        attr_types = (
            _collect_class_attr_types(body_for_attrs, src)
            if body_for_attrs is not None else {}
        )
        if attr_types:
            cls_metadata["attr_types"] = attr_types

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
            metadata=cls_metadata,
        )
        nodes.append(class_node)

        edges.append(Edge(
            src=class_id, dst=parent_id, kind=EdgeKind.DEFINED_IN,
            file=rel, line=node.start_point[0] + 1,
        ))

        self._emit_decorator_calls(node, rel, class_id, src, edges)

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
        metadata: dict[str, object] = {"decorators": decorators}
        if _is_entry_point(
            decorators,
            name,
            extra_decorator_patterns=self.extra_entry_point_decorators,
        ) or name == "__main__":
            metadata["entry_point"] = True

        # DF0: capture parameter descriptors and return-type annotation.
        # Methods skip the leading ``self`` / ``cls`` parameter; classmethods
        # and staticmethods follow the same rule (``cls`` is dropped, the
        # static-method case has no implicit first arg so nothing to skip).
        if params is not None:
            metadata["params"] = _extract_params(
                params, src, skip_self_or_cls=(kind == NodeKind.METHOD),
            )
        else:
            metadata["params"] = []
        return_type_node = node.child_by_field_name("return_type")
        metadata["returns"] = (
            node_text(return_type_node, src) if return_type_node else None
        )

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
            metadata=metadata,
        )
        nodes.append(func_node)

        edges.append(Edge(
            src=func_id, dst=parent_id, kind=EdgeKind.DEFINED_IN,
            file=rel, line=node.start_point[0] + 1,
        ))

        self._emit_decorator_calls(node, rel, func_id, src, edges)

        # DF1 — HTTP route extraction. One ROUTE edge per (method, path);
        # Flask's ``methods=[...]`` expands to multiple edges.
        for spec in _extract_route_specs(decorators):
            self._emit_route_edge(
                spec, func_id, rel, node.start_point[0] + 1,
                nodes, edges,
            )

        if body is not None:
            self._collect_calls(body, rel, func_id, src, edges)
            # DF1 — SQLAlchemy READS_FROM / WRITES_TO. Walk the body for
            # ORM session calls; emits ``unresolved::Model`` edges that
            # the post-build resolver rewrites to real CLASS ids.
            self._collect_sql_io(body, rel, func_id, src, edges)
            # Visit nested defs so their bodies and calls are not lost.
            # The innermost named function owns its calls — that mirrors
            # the runtime attribution and matches what users expect when
            # they ask "who calls X?".
            self._visit_nested_defs(
                body, rel, qualname, func_id, kind == NodeKind.METHOD,
                src, nodes, edges,
            )

    def _visit_nested_defs(
        self,
        block: tree_sitter.Node,
        rel: str,
        parent_qualname: str,
        parent_id: str,
        in_method: bool,
        src: bytes,
        nodes: list[Node],
        edges: list[Edge],
    ) -> None:
        """Recursively register nested function/class definitions.

        Walks the subtree but stops descending into a function or class
        once we have handed it to ``_handle_function`` / ``_handle_class``
        (those handlers will recurse on their own bodies). This mirrors
        ``_visit_block`` but skips top-level statement noise.
        """
        stack: list[tree_sitter.Node] = list(block.children)
        while stack:
            node = stack.pop()
            if node.type == "function_definition":
                # Nested functions are FUNCTION nodes (not METHOD); a method's
                # nested helpers are still locally-scoped functions.
                self._handle_function(
                    node, rel, parent_qualname, parent_id,
                    NodeKind.FUNCTION, src, nodes, edges,
                )
                continue
            if node.type == "class_definition":
                self._handle_class(
                    node, rel, parent_qualname, parent_id,
                    src, nodes, edges,
                )
                continue
            if node.type == "decorated_definition":
                inner = next(
                    (
                        c for c in node.children
                        if c.type in ("function_definition", "class_definition")
                    ),
                    None,
                )
                if inner is not None and inner.type == "function_definition":
                    self._handle_function(
                        inner, rel, parent_qualname, parent_id,
                        NodeKind.FUNCTION, src, nodes, edges,
                    )
                    continue
                if inner is not None:
                    self._handle_class(
                        inner, rel, parent_qualname, parent_id,
                        src, nodes, edges,
                    )
                    continue
            stack.extend(node.children)

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
                    arg_list = child.child_by_field_name("arguments")
                    args: list[str] = []
                    kwargs: dict[str, str] = {}
                    if arg_list is not None:
                        args, kwargs = _extract_call_args(arg_list, src)
                    edges.append(Edge(
                        src=scope_id,
                        dst=f"unresolved::{name}",
                        kind=EdgeKind.CALLS,
                        file=rel,
                        line=child.start_point[0] + 1,
                        metadata={
                            "target_name": name,
                            "args": args,
                            "kwargs": kwargs,
                        },
                    ))
            # ``decorator`` subtrees are handled by ``_emit_decorator_calls``
            # so we attribute decorator factories to the decorated symbol
            # rather than the surrounding scope. Skipping them here avoids
            # double-counting at module level.
            if child.type not in (
                "class_definition", "function_definition", "decorator",
            ):
                stack.extend(child.children)

    def _emit_decorator_calls(
        self,
        def_node: tree_sitter.Node,
        rel: str,
        scope_id: str,
        src: bytes,
        edges: list[Edge],
    ) -> None:
        """Emit a CALLS edge for each decorator on a function or class.

        ``@_register("name")`` and ``@my_decorator(arg)`` are calls — they
        invoke the decorator factory at definition time. Without these edges
        decorator-only functions look unreferenced.
        """
        container = def_node
        if (
            def_node.parent is not None
            and def_node.parent.type == "decorated_definition"
        ):
            container = def_node.parent
        for child in container.children:
            if child.type != "decorator":
                continue
            for sub in child.children:
                # The decorator body is either a bare reference (\`@foo\`)
                # which is not a call we should emit, or a \`call\`
                # (\`@foo("x")\`) — only the latter is a real invocation.
                if sub.type == "call":
                    func_child = sub.child_by_field_name("function")
                    if func_child is None and sub.children:
                        func_child = sub.children[0]
                    if func_child is not None:
                        name = node_text(func_child, src)
                        arg_list = sub.child_by_field_name("arguments")
                        args: list[str] = []
                        kwargs: dict[str, str] = {}
                        if arg_list is not None:
                            args, kwargs = _extract_call_args(arg_list, src)
                        edges.append(Edge(
                            src=scope_id,
                            dst=f"unresolved::{name}",
                            kind=EdgeKind.CALLS,
                            file=rel,
                            line=sub.start_point[0] + 1,
                            metadata={
                                "target_name": name,
                                "args": args,
                                "kwargs": kwargs,
                            },
                        ))

    # --- DF1: route + SQL emission helpers ----------------------------

    def _emit_route_edge(
        self,
        spec: dict[str, str],
        func_id: str,
        rel: str,
        line: int,
        nodes: list[Node],
        edges: list[Edge],
    ) -> None:
        """Create a synthetic route node + ROUTE edge from handler.

        The synthetic node uses ``NodeKind.VARIABLE`` (sentinel — see
        ``metadata.synthetic_kind``). Its id encodes ``METHOD::PATH`` so
        multiple handlers binding the same route share the destination.
        """
        method = spec["method"]
        path = spec["path"]
        synthetic_qualname = f"route::{method}::{path}"
        synthetic_id = f"route::{method}::{path}"
        # Avoid duplicate node emission when multiple handlers in the
        # same file declare the same route — caller reuses the same id.
        if not any(n.id == synthetic_id for n in nodes):
            nodes.append(Node(
                id=synthetic_id,
                kind=NodeKind.VARIABLE,
                name=f"{method} {path}",
                qualname=synthetic_qualname,
                file=rel,
                line_start=line,
                line_end=line,
                language="python",
                metadata={
                    "synthetic_kind": "ROUTE",
                    "method": method,
                    "path": path,
                    "framework": spec["framework"],
                },
            ))
        edges.append(Edge(
            src=func_id,
            dst=synthetic_id,
            kind=EdgeKind.ROUTE,
            file=rel,
            line=line,
            metadata={
                "method": method,
                "path": path,
                "framework": spec["framework"],
            },
        ))

    def _collect_sql_io(
        self,
        body: tree_sitter.Node,
        rel: str,
        scope_id: str,
        src: bytes,
        edges: list[Edge],
    ) -> None:
        """Walk a function body for SQLAlchemy data-access patterns.

        Emits ``READS_FROM`` / ``WRITES_TO`` edges with
        ``dst="unresolved::<ModelName>"`` so the post-build resolver can
        rewrite them to real CLASS node ids by qualname/tail match.
        """
        stack: list[tree_sitter.Node] = list(body.children)
        while stack:
            child = stack.pop()
            if child.type == "call":
                self._maybe_emit_sql_edge(child, rel, scope_id, src, edges)
            # Stop at nested defs — their bodies own their own edges.
            if child.type not in (
                "class_definition", "function_definition", "decorator",
            ):
                stack.extend(child.children)

    def _maybe_emit_sql_edge(
        self,
        call_node: tree_sitter.Node,
        rel: str,
        scope_id: str,
        src: bytes,
        edges: list[Edge],
    ) -> None:
        """Inspect one ``call`` AST node for an SQLAlchemy data-op."""
        func_child = call_node.child_by_field_name("function")
        if func_child is None:
            return
        target = node_text(func_child, src)
        # `Model.query.filter(...)` or `Model.query` — Flask-SQLAlchemy.
        m_query = re.match(
            r"^([A-Z][\w]*)\.query(?:\.|$)", target,
        )
        if m_query:
            model = m_query.group(1)
            edges.append(Edge(
                src=scope_id,
                dst=f"unresolved::{model}",
                kind=EdgeKind.READS_FROM,
                file=rel,
                line=call_node.start_point[0] + 1,
                metadata={
                    "operation": "select",
                    "via": "Model.query",
                    "model_name": model,
                    "target_name": model,
                },
            ))
            return
        # session-style chain — `session.query(Model)`, `db.session.add(...)`.
        if not _is_session_chain(target):
            return
        verb = target.rsplit(".", 1)[-1]
        # session.query(Model) / session.get(Model, id) / .scalars(...)
        if verb in _SQL_READ_OUTER:
            self._emit_sql_from_first_arg(
                call_node, rel, scope_id, src, edges,
                kind=EdgeKind.READS_FROM, operation="select",
                via=f"session.{verb}",
            )
            return
        if verb in _SQL_WRITE_OUTER:
            op = "delete" if verb == "delete" else "insert"
            self._emit_sql_from_first_arg(
                call_node, rel, scope_id, src, edges,
                kind=EdgeKind.WRITES_TO, operation=op,
                via=f"session.{verb}",
            )
            return
        if verb == "execute":
            # session.execute(select(Model)) / insert(Model) / etc.
            self._emit_sql_from_execute(
                call_node, rel, scope_id, src, edges,
            )

    def _emit_sql_from_first_arg(
        self,
        call_node: tree_sitter.Node,
        rel: str,
        scope_id: str,
        src: bytes,
        edges: list[Edge],
        *,
        kind: EdgeKind,
        operation: str,
        via: str,
    ) -> None:
        arg_list = call_node.child_by_field_name("arguments")
        if arg_list is None:
            return
        first_named = next(
            (c for c in arg_list.children if c.is_named), None,
        )
        if first_named is None:
            return
        model = _model_name_from_call_arg(node_text(first_named, src))
        if not model:
            return
        edges.append(Edge(
            src=scope_id,
            dst=f"unresolved::{model}",
            kind=kind,
            file=rel,
            line=call_node.start_point[0] + 1,
            metadata={
                "operation": operation,
                "via": via,
                "model_name": model,
                "target_name": model,
            },
        ))

    def _emit_sql_from_execute(
        self,
        call_node: tree_sitter.Node,
        rel: str,
        scope_id: str,
        src: bytes,
        edges: list[Edge],
    ) -> None:
        """Handle ``session.execute(select|insert|update|delete(Model))``."""
        arg_list = call_node.child_by_field_name("arguments")
        if arg_list is None:
            return
        first_named = next(
            (c for c in arg_list.children if c.is_named), None,
        )
        if first_named is None:
            return
        # Drill through ``.values(...)`` / ``.where(...)`` chains —
        # ``select(Model).where(...)`` keeps wrapping the original
        # constructor call inside ``function -> attribute -> object``.
        first_named = _unwrap_to_root_call(first_named)
        if first_named is None or first_named.type != "call":
            return
        inner_func = first_named.child_by_field_name("function")
        if inner_func is None:
            return
        inner_name = node_text(inner_func, src).rsplit(".", 1)[-1]
        if inner_name in _SQL_READ_INNER:
            kind = EdgeKind.READS_FROM
            operation = "select"
        elif inner_name in _SQL_WRITE_INNER:
            kind = EdgeKind.WRITES_TO
            operation = inner_name
        else:
            return
        inner_args = first_named.child_by_field_name("arguments")
        if inner_args is None:
            return
        first_inner = next(
            (c for c in inner_args.children if c.is_named), None,
        )
        if first_inner is None:
            return
        model = _model_name_from_call_arg(node_text(first_inner, src))
        if not model:
            return
        edges.append(Edge(
            src=scope_id,
            dst=f"unresolved::{model}",
            kind=kind,
            file=rel,
            line=call_node.start_point[0] + 1,
            metadata={
                "operation": operation,
                "via": f"session.execute({inner_name})",
                "model_name": model,
                "target_name": model,
            },
        ))

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
