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


def _extract_types_from_type_node(
    type_node: tree_sitter.Node, src: bytes
) -> list[str]:
    """Return the list of simple type names from a ``type`` AST node.

    Handles three shapes:
    * single identifier / attribute -> one-element list
    * binary union ``A | B | ...`` -> flattened list of operand names
    * subscript ``Union[A, B]`` / ``Optional[A]`` -> list of inner names

    Anything else (string forward refs, generics like ``list[Foo]``)
    returns an empty list — the resolver will simply not bind that
    attribute, which is safe.
    """
    # ``type`` typically has a single inner expression child; descend.
    inner: tree_sitter.Node | None = None
    for c in type_node.children:
        if c.is_named:
            inner = c
            break
    if inner is None:
        return []
    return _flatten_type_expr(inner, src)


def _flatten_type_expr(node: tree_sitter.Node, src: bytes) -> list[str]:
    """Recursively flatten a type expression into bare type names."""
    if node.type in ("identifier", "attribute"):
        return [node_text(node, src)]
    if node.type == "binary_operator":
        # ``A | B`` — only honor union when the operator is ``|``.
        op_is_pipe = any(
            c.type == "|" for c in node.children if not c.is_named
        )
        if not op_is_pipe:
            return []
        out: list[str] = []
        for c in node.children:
            if c.is_named:
                out.extend(_flatten_type_expr(c, src))
        return out
    if node.type in ("subscript", "generic_type"):
        # ``Union[A, B]`` / ``Optional[A]`` — both flatten to operand list.
        # Tree-sitter parses ``Union[A, B]`` as ``generic_type`` with a
        # leading identifier and a ``type_parameter`` child; ``Optional[A]``
        # may be a ``subscript`` depending on grammar version.
        head_node: tree_sitter.Node | None = None
        if node.type == "subscript":
            head_node = node.child_by_field_name("value")
        else:
            for c in node.children:
                if c.type in ("identifier", "attribute"):
                    head_node = c
                    break
        head = node_text(head_node, src) if head_node is not None else ""
        head_leaf = head.rsplit(".", 1)[-1]
        if head_leaf not in ("Union", "Optional"):
            return []
        out2: list[str] = []
        for c in node.children:
            if not c.is_named or c is head_node:
                continue
            if c.type == "type_parameter":
                for inner_c in c.children:
                    if inner_c.is_named:
                        out2.extend(_flatten_type_expr(inner_c, src))
            else:
                out2.extend(_flatten_type_expr(c, src))
        return out2
    if node.type == "type":
        # Wrapping ``type`` node — descend into its named child.
        for c in node.children:
            if c.is_named:
                return _flatten_type_expr(c, src)
        return []
    return []


def _collect_class_attr_types(
    body: tree_sitter.Node, src: bytes
) -> dict[str, list[str]]:
    """Return ``{attr_name: [type_qualname, ...]}`` for class annotations.

    Captures both class-level direct annotations (``svc: Service``,
    ``svc: Foo | Bar``, ``svc: Union[Foo, Bar]``) AND attribute
    assignments inside ``__init__`` (including ``if/else`` branches), so
    a backend-facade pattern like::

        def __init__(self, x):
            if x:
                self._b: Foo = Foo()
            else:
                self._b = Bar()

    yields ``{"_b": ["Foo", "Bar"]}``.
    """
    out: dict[str, list[str]] = {}
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
            attr_name = node_text(name_node, src)
            type_names = _extract_types_from_type_node(type_node, src)
            if not attr_name or not type_names:
                continue
            existing = out.setdefault(attr_name, [])
            for t in type_names:
                if t not in existing:
                    existing.append(t)

    # Walk __init__ for ``self.X = ...`` and ``self.X: T = ...`` bindings.
    for stmt in body.children:
        func: tree_sitter.Node | None = None
        if stmt.type == "function_definition":
            func = stmt
        elif stmt.type == "decorated_definition":
            for c in stmt.children:
                if c.type == "function_definition":
                    func = c
                    break
        if func is None:
            continue
        name_n = func.child_by_field_name("name")
        if name_n is None or node_text(name_n, src) != "__init__":
            continue
        init_body = func.child_by_field_name("body")
        if init_body is None:
            continue
        _collect_self_attr_types_in_block(init_body, src, out)
    return out


def _collect_self_attr_types_in_block(
    block: tree_sitter.Node,
    src: bytes,
    out: dict[str, list[str]],
) -> None:
    """Walk a function body collecting ``self.X[: T] = Y(...)`` bindings.

    Recurses into ``if/else`` (and ``try/with/for/while``) branches so
    both arms of a conditional contribute to the attribute's type list.
    Walrus (``:=``) and dynamic ``setattr`` are deliberately ignored —
    those are R4+ territory.
    """
    for child in block.children:
        if child.type == "expression_statement":
            for assignment in child.children:
                if assignment.type != "assignment":
                    continue
                _maybe_record_self_assign(assignment, src, out)
        elif child.type == "block":
            # Tree-sitter wraps clause bodies in a ``block`` whose entries
            # are the actual statements; recurse straight into it.
            _collect_self_attr_types_in_block(child, src, out)
        elif child.type in (
            "if_statement", "with_statement", "try_statement",
            "for_statement", "while_statement", "elif_clause", "else_clause",
            "except_clause", "finally_clause",
        ):
            # Recurse into all named children — this picks up the clause's
            # inner ``block`` plus any sibling ``elif_clause`` / ``else_clause``
            # / ``except_clause`` chains.
            for sub in child.children:
                if sub.is_named:
                    _collect_self_attr_types_in_block(sub, src, out)


def _maybe_record_self_assign(
    assignment: tree_sitter.Node,
    src: bytes,
    out: dict[str, list[str]],
) -> None:
    """If ``assignment`` is ``self.X[: T] = expr``, record the type(s)."""
    # Find the LHS (attribute), the optional type annotation, and RHS.
    lhs: tree_sitter.Node | None = None
    type_node: tree_sitter.Node | None = None
    rhs: tree_sitter.Node | None = None
    seen_eq = False
    for c in assignment.children:
        if c.type == "=":
            seen_eq = True
            continue
        if c.type == "type":
            type_node = c
            continue
        if not seen_eq:
            if lhs is None:
                lhs = c
        else:
            if rhs is None:
                rhs = c
    if lhs is None or lhs.type != "attribute":
        return
    obj = lhs.child_by_field_name("object")
    attr = lhs.child_by_field_name("attribute")
    if obj is None or attr is None:
        return
    if node_text(obj, src) != "self":
        return
    attr_name = node_text(attr, src)
    if not attr_name:
        return

    type_names: list[str] = []
    if type_node is not None:
        type_names.extend(_extract_types_from_type_node(type_node, src))

    # If no annotation (or annotation gave nothing useful), fall back
    # to the constructor name on the RHS.
    if not type_names and rhs is not None:
        ctor = _ctor_name_from_expr(rhs, src)
        if ctor:
            type_names.append(ctor)

    if not type_names:
        return
    existing = out.setdefault(attr_name, [])
    for t in type_names:
        if t not in existing:
            existing.append(t)


def _ctor_name_from_expr(
    node: tree_sitter.Node, src: bytes
) -> str | None:
    """Return the constructor name from an RHS expression like ``Foo(...)``.

    Handles ``Foo(...)``, ``mod.Foo(...)`` (returns ``Foo``), and simple
    identifier references ``Foo`` (when a name is being aliased without
    instantiation, we still record the type so ``self._b = some_factory``
    style does NOT match — only ``identifier`` / ``attribute`` whose leaf
    looks PascalCase counts as a "type-ish" reference).

    Walrus (``named_expression``) is intentionally skipped.
    """
    if node.type == "call":
        func = node.child_by_field_name("function")
        if func is None:
            return None
        text = node_text(func, src).rsplit(".", 1)[-1]
        if text and text[0].isupper():
            return text
        return None
    return None


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


# Names that look like classes by the capital-letter heuristic but are
# either builtins, stdlib, or typing scaffolding — emitting REFERENCES
# edges to these would be noise. The dead-code analyzer doesn't care
# about them anyway.
_ANNOTATION_NAME_BLOCKLIST: frozenset[str] = frozenset({
    # typing module scaffolding
    "Any", "AnyStr", "Optional", "Union", "Literal", "Final", "ClassVar",
    "Annotated", "TypedDict", "TypeVar", "ParamSpec", "Concatenate",
    "Type", "Tuple", "List", "Dict", "Set", "FrozenSet", "Callable",
    "Iterable", "Iterator", "Generator", "AsyncIterator", "AsyncGenerator",
    "Awaitable", "Coroutine", "AsyncContextManager", "ContextManager",
    "Sequence", "Mapping", "MutableMapping", "MutableSequence", "MutableSet",
    "Hashable", "Sized", "Container", "Collection", "Reversible",
    "NamedTuple", "Self", "Never", "NoReturn", "LiteralString", "NotRequired",
    "Required", "Unpack", "TypeAlias", "TypeGuard", "TypeIs",
    # Pydantic / FastAPI dependency annotations users wrap their types in.
    # We don't want to emit references TO `Body` / `Depends` etc.;
    # we want the inner type names that come along with them.
    "Body", "Depends", "Path", "Query", "Header", "Cookie", "Form", "File",
    "Security", "Request", "Response",
    # Common Python builtins that pass the capital-letter heuristic.
    "True", "False", "None", "Ellipsis", "NotImplemented",
})

_TYPE_NAME_RE = re.compile(r"\b([A-Z][A-Za-z0-9_]*)\b")


def _extract_type_references(annotation: str | None) -> list[str]:
    """Return capitalized type names referenced in an annotation string.

    Splits ``Annotated[User, Body(...)]`` / ``list[User] | None`` /
    ``Optional[User]`` etc. into the candidate names ``User``. Stdlib
    typing scaffolding and FastAPI dependency markers are blocklisted.

    Returns names in source-order with duplicates removed; an empty list
    when ``annotation`` is None or blank.
    """
    if not annotation:
        return []
    seen: set[str] = set()
    out: list[str] = []
    for match in _TYPE_NAME_RE.finditer(annotation):
        name = match.group(1)
        if name in _ANNOTATION_NAME_BLOCKLIST:
            continue
        if name in seen:
            continue
        seen.add(name)
        out.append(name)
    return out


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
    session/db handle (``session.query``, ``db.session.query``, ...).

    Also matches ``self.session.X`` / ``self.db.X`` patterns common in
    repository-style code where the session is held as an instance
    attribute.
    """
    if not target:
        return False
    parts = target.split(".")
    head = parts[0].lower()
    if head in _SESSION_HEAD_TOKENS:
        return True
    # self.<session-token>.X — repository-pattern method bodies.
    if head == "self" and len(parts) >= 2:
        second = parts[1].lower()
        if second in _SESSION_HEAD_TOKENS:
            return True
    return False


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


# --- Public-API pragma detection ----------------------------------------
#
# A function or class can be exempted from dead-code analysis by prefixing
# its definition with one of these pragma comments on the line immediately
# before the def/class (or before the topmost decorator). A trailing
# same-line pragma (``def foo(): ...  # pragma: codegraph-public-api``) is
# also accepted.
_PUBLIC_API_PRAGMAS: tuple[str, ...] = (
    "# pragma: codegraph-public-api",
    "# codegraph: public-api",
)


def _line_has_public_api_pragma(line: str) -> bool:
    stripped = line.strip()
    return any(pragma in stripped for pragma in _PUBLIC_API_PRAGMAS)


def _has_public_api_pragma(def_node: tree_sitter.Node, src: bytes) -> bool:
    """Return True if the def/class node is preceded by a public-API pragma.

    The pragma must sit on the line immediately above the definition (or
    above the topmost decorator, when decorators are present) or as a
    trailing comment on the def/class signature line itself.
    """
    container: tree_sitter.Node = def_node
    if (
        def_node.parent is not None
        and def_node.parent.type == "decorated_definition"
    ):
        container = def_node.parent

    start_byte = container.start_byte
    end_byte = container.end_byte

    # Same-line trailing pragma: scan from the def signature start to the
    # first newline of the def body.
    sig_end = src.find(b"\n", start_byte)
    if sig_end == -1:
        sig_end = end_byte
    sig_line = src[start_byte:sig_end].decode("utf-8", errors="replace")
    if _line_has_public_api_pragma(sig_line):
        return True

    # Walk backward through whitespace-only lines until we find a non-blank
    # line; if that line is a pragma comment, we're matched.
    cursor = start_byte
    # Step back past the leading newline of the def's line.
    if cursor > 0 and src[cursor - 1:cursor] == b"\n":
        cursor -= 1
    while cursor > 0:
        # Find the start of the previous line.
        prev_nl = src.rfind(b"\n", 0, cursor)
        line_start = prev_nl + 1 if prev_nl != -1 else 0
        line = src[line_start:cursor].decode("utf-8", errors="replace")
        if not line.strip():
            # Blank line — keep walking.
            cursor = prev_nl
            if cursor <= 0:
                return False
            continue
        return _line_has_public_api_pragma(line)
    return False


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

    # Kill-switch for intra-procedural data-flow edge emission (C1).
    # Set to False to disable DATA_ASSIGN / DATA_ARG / DATA_RETURN edges
    # and PARAMETER node emission entirely. Attribute hook for future config
    # file plumbing — the builder's _apply_config_to_extractors can flip it.
    emit_data_edges: bool = True

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
        if _has_public_api_pragma(node, src):
            cls_metadata["public_api"] = True

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
        if _has_public_api_pragma(node, src):
            metadata["public_api"] = True

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

        # Emit reference edges for each capitalized type name appearing in
        # parameter annotations and the return type. The resolver rewrites
        # ``unresolved::<TypeName>`` to the real CLASS id if the type is
        # defined in the repo. This keeps dead-code detection honest for
        # types that are only referenced via type annotations — most
        # notably FastAPI Pydantic request-body models, which would
        # otherwise look unreferenced because handler dispatch happens
        # via parameter annotations rather than direct calls.
        annotation_strs: list[str] = []
        params_meta = metadata.get("params")
        if isinstance(params_meta, list):
            for param in params_meta:
                if isinstance(param, dict):
                    type_str = param.get("type")
                    if isinstance(type_str, str):
                        annotation_strs.append(type_str)
        return_meta = metadata.get("returns")
        if isinstance(return_meta, str):
            annotation_strs.append(return_meta)
        emitted: set[str] = set()
        for ann in annotation_strs:
            for type_name in _extract_type_references(ann):
                if type_name in emitted:
                    continue
                emitted.add(type_name)
                edges.append(Edge(
                    src=func_id,
                    dst=f"unresolved::{type_name}",
                    kind=EdgeKind.CALLS,
                    file=rel,
                    line=node.start_point[0] + 1,
                    metadata={"target_name": type_name, "via": "annotation"},
                ))

        # DF1 — HTTP route extraction. One ROUTE edge per (method, path);
        # Flask's ``methods=[...]`` expands to multiple edges.
        for spec in _extract_route_specs(decorators):
            self._emit_route_edge(
                spec, func_id, rel, node.start_point[0] + 1,
                nodes, edges,
            )

        # C1 — PARAMETER nodes + intra-procedural data edges.
        # Emit one PARAMETER node per logical parameter (already filtered by
        # skip_self_or_cls in metadata["params"]).  We also collect the raw
        # params_node here so we can correlate line numbers.
        param_scope: dict[str, str] = {}  # name → node-id for data-edge seeding
        if self.emit_data_edges and params is not None:
            param_scope = self._emit_param_nodes(
                params, src, rel, qualname, func_id,
                kind == NodeKind.METHOD, node.start_point[0] + 1,
                nodes, edges,
            )

        if body is not None:
            self._collect_calls(body, rel, func_id, src, edges)
            # DF1 — SQLAlchemy READS_FROM / WRITES_TO. Walk the body for
            # ORM session calls; emits ``unresolved::Model`` edges that
            # the post-build resolver rewrites to real CLASS ids.
            self._collect_sql_io(body, rel, func_id, src, edges)
            # C1 — intra-procedural data-flow edges (DATA_ASSIGN/ARG/RETURN).
            if self.emit_data_edges:
                self._collect_data_edges(
                    body, rel, func_id, qualname, src, param_scope, nodes, edges,
                )
            # Visit nested defs so their bodies and calls are not lost.
            # The innermost named function owns its calls — that mirrors
            # the runtime attribution and matches what users expect when
            # they ask "who calls X?".
            self._visit_nested_defs(
                body, rel, qualname, func_id, kind == NodeKind.METHOD,
                src, nodes, edges,
            )

    def _emit_param_nodes(
        self,
        params_node: tree_sitter.Node,
        src: bytes,
        rel: str,
        func_qualname: str,
        func_id: str,
        skip_self_or_cls: bool,
        func_line: int,
        nodes: list[Node],
        edges: list[Edge],
    ) -> dict[str, str]:
        """Emit a PARAMETER node and PARAM_OF edge for each function parameter.

        Returns a scope seed dict ``{param_name: param_node_id}`` for use by
        ``_collect_data_edges``.

        Limitations (documented):
        - Variadic params (*args, **kwargs) are included with their prefixed
          names and cannot be individually resolved in the data-flow scope.
        - self/cls is skipped for methods, consistent with DF0 behaviour.
        """
        scope: dict[str, str] = {}
        first_seen = False
        index = 0
        for child in params_node.children:
            if not child.is_named:
                continue
            # Determine name, type, line from the parameter AST node.
            param_name: str | None = None
            param_type: str | None = None
            param_line = child.start_point[0] + 1
            if child.type == "identifier":
                param_name = node_text(child, src)
            elif child.type == "typed_parameter":
                name_n = next(
                    (c for c in child.children if c.type == "identifier"), None
                )
                type_n = next(
                    (c for c in child.children if c.type == "type"), None
                )
                if name_n is not None:
                    param_name = node_text(name_n, src)
                    param_type = node_text(type_n, src) if type_n else None
            elif child.type == "default_parameter":
                name_n = child.child_by_field_name("name")
                if name_n is not None:
                    param_name = node_text(name_n, src)
            elif child.type == "typed_default_parameter":
                name_n = child.child_by_field_name("name")
                type_n = child.child_by_field_name("type")
                if name_n is not None:
                    param_name = node_text(name_n, src)
                    param_type = node_text(type_n, src) if type_n else None
            elif child.type == "list_splat_pattern":
                inner = next(
                    (c for c in child.children if c.type == "identifier"), None
                )
                if inner is not None:
                    param_name = f"*{node_text(inner, src)}"
            elif child.type == "dictionary_splat_pattern":
                inner = next(
                    (c for c in child.children if c.type == "identifier"), None
                )
                if inner is not None:
                    param_name = f"**{node_text(inner, src)}"
            if param_name is None:
                continue
            if (
                skip_self_or_cls
                and not first_seen
                and param_name in ("self", "cls")
            ):
                first_seen = True
                continue
            first_seen = True
            param_qualname = f"{func_qualname}.<param:{param_name}>"
            param_id = make_node_id(NodeKind.PARAMETER, param_qualname, rel)
            nodes.append(Node(
                id=param_id,
                kind=NodeKind.PARAMETER,
                name=param_name,
                qualname=param_qualname,
                file=rel,
                line_start=param_line,
                line_end=param_line,
                language="python",
                metadata={
                    "index": index,
                    "name": param_name,
                    "type": param_type,
                },
            ))
            edges.append(Edge(
                src=param_id,
                dst=func_id,
                kind=EdgeKind.PARAM_OF,
                file=rel,
                line=func_line,
            ))
            # Seed the scope with the bare name (strip variadic prefix for
            # *args/**kwargs so callers referencing ``args`` in the body work).
            bare_name = param_name.lstrip("*")
            if bare_name:
                scope[bare_name] = param_id
            index += 1
        return scope

    def _collect_data_edges(
        self,
        body: tree_sitter.Node,
        rel: str,
        func_id: str,
        func_qualname: str,
        src: bytes,
        param_scope: dict[str, str],
        nodes: list[Node],
        edges: list[Edge],
    ) -> None:
        """Walk a function body and emit intra-procedural data-flow edges.

        Emits DATA_ASSIGN, DATA_ARG, and DATA_RETURN edges for simple scalar
        variable flow within a single function.  The scope maps variable names
        to their most-recent definition node-id (a PARAMETER or VARIABLE node).

        **Design decisions / limitations (intentional simplifications)**:

        * Single-level shadowing by line: ``x = a; x = b`` emits two distinct
          VARIABLE nodes qualified by line, so shadow chains are traceable.
        * No attribute tracking: ``obj.field = x`` is not captured.
        * No tuple unpacking: ``a, b = f()`` — the first target only is taken
          when the LHS is a tuple; the others are skipped.
        * Comprehension scopes: treated as part of the surrounding function
          scope (no inner binding isolation).
        * Calls in RHS: ``x = foo(a)`` emits DATA_ASSIGN from the synthetic
          sentinel ``unresolved::ret::foo`` → VARIABLE x, metadata
          ``{"callee": "foo"}``.  Cross-file binding of the sentinel to the
          callee's return node happens in a later PR.
        * Only plain identifiers in RHS are tracked — binary ops, subscripts,
          and attribute access on in-scope names do NOT propagate.  This keeps
          the implementation correct (no false positives) at the cost of
          missing some true positives.
        """
        # Mutable scope: maps current name → most recent PARAMETER/VARIABLE id.
        scope: dict[str, str] = dict(param_scope)
        # Track the return-sentinel node-id lazily (emit once per function).
        return_node_id: str | None = None

        # Walk statements in document order to maintain correct scope.
        # We use a recursive helper to preserve forward-order processing
        # while descending into control-flow blocks.
        return_node_id = self._walk_data_stmts(
            list(body.children), rel, func_id, func_qualname, src,
            scope, return_node_id, nodes, edges,
        )

    def _walk_data_stmts(
        self,
        stmts: list[tree_sitter.Node],
        rel: str,
        func_id: str,
        func_qualname: str,
        src: bytes,
        scope: dict[str, str],
        return_node_id: str | None,
        nodes: list[Node],
        edges: list[Edge],
    ) -> str | None:
        """Walk *stmts* in document order, updating scope and emitting data edges.

        Returns the (possibly newly created) return-sentinel node-id.
        """
        for stmt in stmts:
            # --- assignment: x = expr  (and annotated: x: T = expr) ------
            if stmt.type == "expression_statement":
                inner = next((c for c in stmt.children if c.is_named), None)
                if inner is not None and inner.type in (
                    "assignment", "augmented_assignment",
                ):
                    self._handle_data_assign(
                        inner, rel, func_id, func_qualname, src, scope,
                        nodes, edges,
                    )
                elif inner is not None and inner.type == "call":
                    # Standalone call statement: ``g(x)`` / ``g(user=x)``.
                    # Emit DATA_ARG edges for in-scope identifier arguments.
                    func_child = inner.child_by_field_name("function")
                    callee_text = (
                        node_text(func_child, src) if func_child else "<expr>"
                    )
                    arg_list = inner.child_by_field_name("arguments")
                    if arg_list is not None:
                        self._emit_arg_edges(
                            arg_list, callee_text, rel, src, scope, edges,
                            inner.start_point[0] + 1,
                        )

            # --- return expr -----------------------------------------------
            elif stmt.type == "return_statement":
                return_node_id = self._handle_data_return(
                    stmt, rel, func_qualname, src, scope,
                    return_node_id, nodes, edges,
                )

            # --- for target: ``for x in iterable:`` ------------------------
            # The loop variable is a definition fed by the iterable —
            # conservative element-of propagation (taint on the collection
            # taints the element). Critical for source patterns like
            # ``for url in scraped_urls: fetch(url)``.
            elif stmt.type == "for_statement":
                self._handle_for_target(
                    stmt, rel, func_id, func_qualname, src, scope,
                    nodes, edges,
                )
                body = stmt.child_by_field_name("body")
                if body is not None:
                    return_node_id = self._walk_data_stmts(
                        list(body.children), rel, func_id, func_qualname,
                        src, scope, return_node_id, nodes, edges,
                    )

            # Descend into control-flow blocks but stop at nested defs.
            # We preserve document order by recursing rather than stacking.
            elif stmt.type not in (
                "function_definition", "class_definition", "decorator",
            ):
                for child in stmt.children:
                    if child.type == "block":
                        return_node_id = self._walk_data_stmts(
                            list(child.children), rel, func_id, func_qualname,
                            src, scope, return_node_id, nodes, edges,
                        )
                    elif child.type in (
                        "if_statement", "for_statement", "while_statement",
                        "with_statement", "try_statement",
                        "expression_statement", "return_statement",
                    ):
                        return_node_id = self._walk_data_stmts(
                            [child], rel, func_id, func_qualname,
                            src, scope, return_node_id, nodes, edges,
                        )
        return return_node_id

    def _handle_data_assign(
        self,
        assign_node: tree_sitter.Node,
        rel: str,
        func_id: str,
        func_qualname: str,
        src: bytes,
        scope: dict[str, str],
        nodes: list[Node],
        edges: list[Edge],
    ) -> None:
        """Process one assignment or augmented-assignment statement."""
        line = assign_node.start_point[0] + 1

        if assign_node.type == "augmented_assignment":
            # ``x += rhs`` — treat as rhs → x, but x must already be in scope
            # (we don't re-define it since aug-assign modifies in place).
            lhs_node = assign_node.child_by_field_name("left")
            rhs_node = assign_node.child_by_field_name("right")
            if lhs_node is None or rhs_node is None:
                return
            lhs_name = (
                node_text(lhs_node, src)
                if lhs_node.type == "identifier"
                else None
            )
            if lhs_name is None or lhs_name not in scope:
                return
            var_id = scope[lhs_name]
            self._emit_rhs_edges(
                rhs_node, rel, var_id, func_qualname, src, scope, edges, line,
            )
            return

        # Standard assignment (covers plain ``x = y`` and annotated ``x: T = y``).
        # LHS: use the first simple identifier target.
        lhs_node = assign_node.child_by_field_name("left")
        rhs_node = assign_node.child_by_field_name("right")
        # Also handle annotated assignment where the field name is "name"
        # (tree-sitter grammar variation).
        if lhs_node is None:
            lhs_node = next(
                (
                    c for c in assign_node.children
                    if c.is_named and c.type == "identifier"
                ),
                None,
            )
        if rhs_node is None or lhs_node is None:
            return

        # Tuple unpacking — take first simple identifier only.
        if lhs_node.type in ("tuple_pattern", "tuple"):
            lhs_node = next(
                (c for c in lhs_node.children if c.is_named and c.type == "identifier"),
                None,
            )
        if lhs_node is None or lhs_node.type != "identifier":
            return

        lhs_name = node_text(lhs_node, src)
        if not lhs_name:
            return

        # Create a new VARIABLE node (line-qualified so shadowing is distinct).
        var_qualname = f"{func_qualname}.<var:{lhs_name}:{line}>"
        var_id = make_node_id(NodeKind.VARIABLE, var_qualname, rel)
        nodes.append(Node(
            id=var_id,
            kind=NodeKind.VARIABLE,
            name=lhs_name,
            qualname=var_qualname,
            file=rel,
            line_start=line,
            line_end=line,
            language="python",
            metadata={"assigned_in": func_qualname},
        ))
        edges.append(Edge(
            src=var_id,
            dst=func_id,
            kind=EdgeKind.DEFINED_IN,
            file=rel,
            line=line,
        ))

        # Update scope BEFORE emitting RHS edges so self-referential
        # assignments (``x = x + 1``) use the *old* binding for the RHS.
        old_id = scope.get(lhs_name)
        scope[lhs_name] = var_id

        self._emit_rhs_edges(
            rhs_node, rel, var_id, func_qualname, src,
            # Use scope snapshot with old binding for the RHS reads.
            {**scope, lhs_name: old_id} if old_id else scope,
            edges, line,
        )

    def _handle_for_target(
        self,
        for_node: tree_sitter.Node,
        rel: str,
        func_id: str,
        func_qualname: str,
        src: bytes,
        scope: dict[str, str],
        nodes: list[Node],
        edges: list[Edge],
    ) -> None:
        """Register a for-loop target as a scoped VARIABLE fed by its iterable.

        ``for x in items`` emits DATA_ASSIGN edges from in-scope identifiers
        inside ``items`` to a new VARIABLE node for ``x`` (element-of
        propagation). Tuple targets take the first simple identifier only,
        mirroring :meth:`_handle_data_assign`.
        """
        left = for_node.child_by_field_name("left")
        right = for_node.child_by_field_name("right")
        if left is not None and left.type in ("tuple_pattern", "tuple", "pattern_list"):
            left = next(
                (c for c in left.children if c.is_named and c.type == "identifier"),
                None,
            )
        if left is None or left.type != "identifier":
            return
        name = node_text(left, src)
        if not name:
            return
        line = left.start_point[0] + 1
        var_qualname = f"{func_qualname}.<var:{name}:{line}>"
        var_id = make_node_id(NodeKind.VARIABLE, var_qualname, rel)
        nodes.append(Node(
            id=var_id,
            kind=NodeKind.VARIABLE,
            name=name,
            qualname=var_qualname,
            file=rel,
            line_start=line,
            line_end=line,
            language="python",
            metadata={"assigned_in": func_qualname, "loop_target": True},
        ))
        edges.append(Edge(
            src=var_id,
            dst=func_id,
            kind=EdgeKind.DEFINED_IN,
            file=rel,
            line=line,
        ))
        if right is not None:
            self._emit_rhs_edges(
                right, rel, var_id, func_qualname, src, scope, edges, line,
            )
        scope[name] = var_id

    def _emit_rhs_edges(
        self,
        rhs_node: tree_sitter.Node,
        rel: str,
        dst_id: str,
        func_qualname: str,
        src: bytes,
        scope: dict[str, str],
        edges: list[Edge],
        line: int,
    ) -> None:
        """Emit DATA_ASSIGN edges from identifiers/call-results in *rhs_node*.

        Walks the RHS expression tree collecting:
        * Plain identifier → DATA_ASSIGN if name is in scope.
        * ``call`` node → DATA_ASSIGN from the sentinel
          ``unresolved::ret::<callee>``, and also DATA_ARG edges for each
          plain-identifier argument that resolves in scope.
        """
        # BFS over the RHS to collect all identifiers and calls.
        rhs_stack = [rhs_node]
        while rhs_stack:
            node = rhs_stack.pop()
            if node.type == "identifier":
                name = node_text(node, src)
                if name and name in scope and scope[name] is not None:
                    edges.append(Edge(
                        src=scope[name],
                        dst=dst_id,
                        kind=EdgeKind.DATA_ASSIGN,
                        file=rel,
                        line=line,
                    ))
            elif node.type == "call":
                func_child = node.child_by_field_name("function")
                callee_text = node_text(func_child, src) if func_child else "<expr>"
                # DATA_ASSIGN from return-value sentinel.
                edges.append(Edge(
                    src=f"unresolved::ret::{callee_text}",
                    dst=dst_id,
                    kind=EdgeKind.DATA_ASSIGN,
                    file=rel,
                    line=line,
                    metadata={"callee": callee_text},
                ))
                # DATA_ARG edges for in-scope arguments.
                arg_list = node.child_by_field_name("arguments")
                if arg_list is not None:
                    self._emit_arg_edges(
                        arg_list, callee_text, rel, src, scope, edges, line,
                    )
                # Do NOT recurse into nested calls via rhs_stack here — the
                # call itself already represents the value, and recursing
                # would incorrectly attribute identifier nodes inside the
                # argument list as direct sources of dst_id.
                continue
            else:
                rhs_stack.extend(c for c in node.children if c.is_named)

    def _emit_arg_edges(
        self,
        arg_list: tree_sitter.Node,
        callee_text: str,
        rel: str,
        src: bytes,
        scope: dict[str, str],
        edges: list[Edge],
        line: int,
    ) -> None:
        """Emit DATA_ARG edges for plain-identifier arguments in a call.

        Cross-file binding of the sentinel dst to the callee's PARAMETER node
        is deferred to a later PR.  Here we emit unresolved sentinels of the
        form ``unresolved::arg::<callee>::<position_or_kwarg>``.

        Limitations: only plain identifier arguments produce edges; complex
        expressions (``f(a + b)``, ``f(obj.attr)``) are silently skipped.
        """
        pos = 0
        for child in arg_list.children:
            if not child.is_named:
                continue
            if child.type == "keyword_argument":
                kw_name_n = child.child_by_field_name("name")
                kw_val_n = child.child_by_field_name("value")
                if (
                    kw_name_n is not None
                    and kw_val_n is not None
                    and kw_val_n.type == "identifier"
                ):
                    arg_name = node_text(kw_val_n, src)
                    kw = node_text(kw_name_n, src)
                    if arg_name and arg_name in scope and scope[arg_name] is not None:
                        edges.append(Edge(
                            src=scope[arg_name],
                            dst=f"unresolved::arg::{callee_text}::{kw}",
                            kind=EdgeKind.DATA_ARG,
                            file=rel,
                            line=line,
                            metadata={
                                "callee": callee_text,
                                "kwarg": kw,
                                "call_line": line,
                            },
                        ))
            elif child.type == "identifier":
                arg_name = node_text(child, src)
                if arg_name and arg_name in scope and scope[arg_name] is not None:
                    edges.append(Edge(
                        src=scope[arg_name],
                        dst=f"unresolved::arg::{callee_text}::{pos}",
                        kind=EdgeKind.DATA_ARG,
                        file=rel,
                        line=line,
                        metadata={
                            "callee": callee_text,
                            "position": pos,
                            "call_line": line,
                        },
                    ))
                pos += 1
            else:
                pos += 1

    def _handle_data_return(
        self,
        return_node: tree_sitter.Node,
        rel: str,
        func_qualname: str,
        src: bytes,
        scope: dict[str, str],
        return_node_id: str | None,
        nodes: list[Node],
        edges: list[Edge],
    ) -> str | None:
        """Emit DATA_RETURN edges from in-scope identifiers in a return expr.

        The synthetic return sentinel node (kind VARIABLE,
        qualname ``<func>.<return>``) is created lazily on first return
        encountered and reused for all subsequent returns in the same function.

        Returns the sentinel's node-id (possibly newly created).
        """
        # Find the expression being returned.
        expr_node = next(
            (c for c in return_node.children if c.is_named and c.type != "return"),
            None,
        )
        if expr_node is None:
            return return_node_id

        # Collect plain identifiers in the return expression.
        id_names: list[str] = []
        expr_stack = [expr_node]
        while expr_stack:
            n = expr_stack.pop()
            if n.type == "identifier":
                id_names.append(node_text(n, src))
            else:
                expr_stack.extend(c for c in n.children if c.is_named)

        sources = [
            scope[nm] for nm in id_names
            if nm in scope and scope[nm] is not None
        ]
        if not sources:
            return return_node_id

        # Create return sentinel node lazily.
        if return_node_id is None:
            ret_qualname = f"{func_qualname}.<return>"
            return_node_id = make_node_id(NodeKind.VARIABLE, ret_qualname, rel)
            nodes.append(Node(
                id=return_node_id,
                kind=NodeKind.VARIABLE,
                name="<return>",
                qualname=ret_qualname,
                file=rel,
                line_start=return_node.start_point[0] + 1,
                line_end=return_node.start_point[0] + 1,
                language="python",
                metadata={"synthetic_kind": "RETURN", "func": func_qualname},
            ))

        line = return_node.start_point[0] + 1
        for src_id in sources:
            edges.append(Edge(
                src=src_id,
                dst=return_node_id,
                kind=EdgeKind.DATA_RETURN,
                file=rel,
                line=line,
            ))
        return return_node_id

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

    # Python loop node types that increase loop depth for their children.
    _PY_LOOP_TYPES: frozenset[str] = frozenset(
        {"for_statement", "while_statement"}
    )

    def _collect_calls(
        self,
        node: tree_sitter.Node,
        rel: str,
        scope_id: str,
        src: bytes,
        edges: list[Edge],
    ) -> None:
        """Walk subtree collecting call expressions, stopping at nested defs."""
        stack: list[tuple[tree_sitter.Node, int]] = [
            (child, 0) for child in node.children
        ]
        while stack:
            child, depth = stack.pop()
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
                            "loop_depth": depth,
                            "in_loop": depth > 0,
                        },
                    ))
            # ``decorator`` subtrees are handled by ``_emit_decorator_calls``
            # so we attribute decorator factories to the decorated symbol
            # rather than the surrounding scope. Skipping them here avoids
            # double-counting at module level.
            if child.type not in (
                "class_definition", "function_definition", "decorator",
            ):
                child_depth = (
                    depth + 1 if child.type in self._PY_LOOP_TYPES else depth
                )
                stack.extend((gc, child_depth) for gc in child.children)

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
