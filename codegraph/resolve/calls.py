"""Post-build cross-file resolution.

Extractors emit edges with ``dst="unresolved::<target_name>"`` whenever the
extractor cannot determine the call/import target without seeing the full
module graph. This pass walks every unresolved edge and tries to rewrite it
into a real node id using a few cheap heuristics:

* ``self.foo`` inside a method -> sibling method on the enclosing class
* bare ``foo`` inside a module/function -> function/class in the same module
* ``mod.foo`` -> resolved through the module's IMPORTS edges
* fully-qualified name -> exact qualname match
* otherwise: unique tail/qualname match across the whole graph

Anything that cannot be resolved unambiguously is left as ``unresolved::*`` so
later analyses can still ignore it without crashing.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from codegraph.graph.schema import Edge, EdgeKind, Node, NodeKind
from codegraph.graph.store_sqlite import SQLiteGraphStore

_REFERENCE_KINDS: frozenset[EdgeKind] = frozenset(
    {
        EdgeKind.CALLS, EdgeKind.IMPORTS, EdgeKind.INHERITS,
        EdgeKind.IMPLEMENTS,
        # DF1 — SQLAlchemy data-access edges. Emitted unresolved by the
        # Python parser (model name only) and rewritten here when a
        # matching CLASS exists in-repo.
        EdgeKind.READS_FROM, EdgeKind.WRITES_TO,
    }
)
# Edge kinds that the DF1 spec requires to be DROPPED when they cannot
# be resolved (rather than left as ``unresolved::*`` for downstream tools).
_DROP_IF_UNRESOLVED: frozenset[EdgeKind] = frozenset(
    {EdgeKind.READS_FROM, EdgeKind.WRITES_TO}
)
_DEFINITION_KINDS: frozenset[NodeKind] = frozenset(
    {NodeKind.FUNCTION, NodeKind.METHOD, NodeKind.CLASS, NodeKind.MODULE}
)


@dataclass
class ResolveStats:
    inspected: int = 0
    resolved: int = 0
    unresolved: int = 0


def _strip_unresolved(dst: str) -> str:
    prefix = "unresolved::"
    return dst[len(prefix):] if dst.startswith(prefix) else dst


def _normalize_target(name: str) -> str:
    """Strip call-syntax noise so "foo.bar()" / "foo()" become "foo.bar".

    Also collapses fresh-instance chains like ``Builder().make`` /
    ``Builder(...).run.bar`` into ``Builder.make`` / ``Builder.run.bar``,
    so the resolver can find the method on the constructed class instead
    of the class itself.
    """
    cleaned = name.strip()
    if cleaned.startswith("await "):
        cleaned = cleaned[len("await "):]
    if cleaned.startswith("new "):
        cleaned = cleaned[len("new "):]
    # Collapse balanced ``(...)`` segments. We track depth so nested
    # parens (``Builder(Inner()).make``) collapse correctly to
    # ``Builder.make``.
    out: list[str] = []
    depth = 0
    for ch in cleaned:
        if ch == "(":
            depth += 1
            continue
        if ch == ")":
            if depth > 0:
                depth -= 1
            continue
        if depth == 0:
            out.append(ch)
    cleaned = "".join(out).strip()
    # Drop any trailing dots left over from ``Foo().``.
    while cleaned.endswith("."):
        cleaned = cleaned[:-1]
    return cleaned


class _Index:
    def __init__(self, nodes: list[Node]) -> None:
        self.by_id: dict[str, Node] = {n.id: n for n in nodes}
        self.by_qualname: dict[str, list[Node]] = defaultdict(list)
        self.by_name: dict[str, list[Node]] = defaultdict(list)
        self.module_by_qualname: dict[str, Node] = {}
        self.module_by_file: dict[str, Node] = {}
        for node in nodes:
            if node.kind in _DEFINITION_KINDS:
                self.by_qualname[node.qualname].append(node)
                self.by_name[node.name].append(node)
            if node.kind == NodeKind.MODULE:
                self.module_by_qualname[node.qualname] = node
                self.module_by_file[node.file] = node


def _attr_type_names(
    class_node: Node, attr_head: str
) -> list[str]:
    """Return the list of declared type names for ``self.<attr_head>``.

    Tolerates the legacy schema where ``attr_types[name]`` was a single
    string rather than a list (R2). Empty list if the attribute is not
    annotated.
    """
    attr_types = class_node.metadata.get("attr_types")
    if not isinstance(attr_types, dict):
        return []
    raw = attr_types.get(attr_head)
    if isinstance(raw, str):
        return [raw] if raw else []
    if isinstance(raw, list):
        return [t for t in raw if isinstance(t, str) and t]
    return []


def _resolve_self_attr_targets(
    class_qual: str,
    head: str,
    tail: str,
    index: _Index,
    imports_for_module: dict[str, dict[str, str]],
    src_module: Node | None,
) -> list[Node]:
    """Resolve ``self.<head>.<tail>`` to one or more candidate nodes.

    Honors a list of candidate type names declared on the enclosing class
    (R3 union annotation or if/else branch assignment in ``__init__``)
    and returns one resolved node per type that owns ``tail``.
    """
    class_nodes = index.by_qualname.get(class_qual, [])
    if not class_nodes:
        return []
    type_names = _attr_type_names(class_nodes[0], head)
    if not type_names:
        return []
    out: list[Node] = []
    seen: set[str] = set()
    for type_name in type_names:
        node = _resolve_typed_attr_tail(
            type_name, tail, index, imports_for_module, src_module,
        )
        if node is not None and node.id not in seen:
            seen.add(node.id)
            out.append(node)
    return out


def _resolve_typed_attr_tail(
    type_name: str,
    tail: str,
    index: _Index,
    imports_for_module: dict[str, dict[str, str]],
    src_module: Node | None,
) -> Node | None:
    """Resolve ``<type_name>.<tail>`` via fully-qualified, import, or tail."""
    # 1) Fully-qualified.
    full = f"{type_name}.{tail}"
    hit = index.by_qualname.get(full, [])
    if hit:
        return hit[0]
    # 2) Import binding from the same module.
    if src_module is not None:
        bind = imports_for_module.get(src_module.id, {})
        bound = bind.get(type_name)
        if bound:
            hit = index.by_qualname.get(f"{bound}.{tail}", [])
            if hit:
                return hit[0]
    # 3) Tail-match: any class whose qualname ends with ``type_name``.
    for qn in index.by_qualname:
        if qn == type_name or qn.endswith("." + type_name):
            hit = index.by_qualname.get(f"{qn}.{tail}", [])
            if hit:
                return hit[0]
    return None


def _try_multi_self_attr(
    target: str,
    src_node: Node | None,
    edge_kind: EdgeKind,
    index: _Index,
    imports_for_module: dict[str, dict[str, str]],
) -> list[Node]:
    """Return >=2 candidate nodes when ``self.X.tail`` has a union type.

    Returns an empty list when the target is not a self-attribute chain,
    when the enclosing class doesn't declare a union for ``X``, or when
    only zero/one type resolves. The single-candidate path is left to
    the regular ``_resolve_target`` logic so we don't double-resolve.
    """
    if edge_kind != EdgeKind.CALLS:
        return []
    if src_node is None or src_node.kind != NodeKind.METHOD:
        return []
    cleaned = _normalize_target(target)
    if not cleaned.startswith("self."):
        return []
    rest = cleaned[len("self."):]
    head, _, tail = rest.partition(".")
    if not tail:
        return []
    parts = src_node.qualname.split(".")
    if len(parts) < 2:
        return []
    class_qual = ".".join(parts[:-1])
    src_module = index.module_by_file.get(src_node.file)
    multi = _resolve_self_attr_targets(
        class_qual, head, tail, index, imports_for_module, src_module,
    )
    if len(multi) < 2:
        return []
    return multi


def _resolve_target(
    target: str,
    src_node: Node | None,
    index: _Index,
    imports_for_module: dict[str, dict[str, str]],
) -> Node | None:
    """Return the best-matching node for ``target``, or None."""
    if not target:
        return None
    target = _normalize_target(target)
    if not target:
        return None

    src_module: Node | None = None
    if src_node is not None:
        src_module = index.module_by_file.get(src_node.file)

    # 1. self.X -> derive enclosing class qualname from src qualname.
    # For `self.foo.bar` style chains, only the first segment after `self.`
    # is meaningfully resolvable against the enclosing class; the deeper
    # tail (`.bar`) requires variable-type inference (R3). So we look up
    # `class_qual.first_segment` and fall through to the remaining
    # heuristics with the first segment as the new target rather than
    # constructing a phantom dotted qualname.
    if target.startswith("self."):
        rest = target[len("self."):]
        head = rest.split(".", 1)[0]
        tail = rest[len(head) + 1:] if len(rest) > len(head) else ""
        if src_node is not None and src_node.kind == NodeKind.METHOD:
            parts = src_node.qualname.split(".")
            if len(parts) >= 2:
                class_qual = ".".join(parts[:-1])
                # Direct match (no dotted tail).
                cands = index.by_qualname.get(f"{class_qual}.{rest}", [])
                if cands:
                    return cands[0]
                # Dotted tail: try resolving via class-level type annotation
                # (\`name: TypeName\` in the class body). If the enclosing
                # class declares ``head: TypeName``, look up
                # ``TypeName.<tail>`` against in-repo types. Multi-type
                # candidates (R3 union / if-else) are returned via
                # ``_resolve_self_attr_targets`` instead.
                if tail:
                    multi = _resolve_self_attr_targets(
                        class_qual, head, tail, index,
                        imports_for_module, src_module,
                    )
                    if multi:
                        return multi[0]
                # Dotted tail: try resolving just the first segment as a
                # method/attribute on the enclosing class.
                if head != rest:
                    cands = index.by_qualname.get(
                        f"{class_qual}.{head}", []
                    )
                    if cands:
                        return cands[0]
        # Fall through with just the head; never let "foo.bar" leak as a
        # phantom qualname into later heuristics.
        target = head

    # 1b. Scope-relative: when the caller is itself a function/method and
    # the target names a function defined directly inside the caller (a
    # nested helper), prefer that closure-local definition over any
    # module-level same-name function.
    if (
        src_node is not None
        and src_node.kind in (NodeKind.FUNCTION, NodeKind.METHOD)
    ):
        nested_q = f"{src_node.qualname}.{target}"
        cands = index.by_qualname.get(nested_q, [])
        if cands:
            return cands[0]

    # 2. Exact qualname.
    if target in index.by_qualname:
        cands = index.by_qualname[target]
        if len(cands) == 1:
            return cands[0]

    # 3. Same-module: <src_module>.<target>.
    if src_module is not None:
        candidate_q = f"{src_module.qualname}.{target}"
        cands = index.by_qualname.get(candidate_q, [])
        if cands:
            return cands[0]

    # 4. Through imports of the source module.
    if src_module is not None:
        bindings = imports_for_module.get(src_module.id, {})
        head, _, tail = target.partition(".")
        bound = bindings.get(head)
        if bound is not None:
            full = bound if not tail else f"{bound}.{tail}"
            cands = index.by_qualname.get(full, [])
            if cands:
                return cands[0]
            mod = index.module_by_qualname.get(bound)
            if mod is not None and tail:
                cands = index.by_qualname.get(f"{mod.qualname}.{tail}", [])
                if cands:
                    return cands[0]

    # 5. Module by qualname (for IMPORTS).
    mod = index.module_by_qualname.get(target)
    if mod is not None:
        return mod

    # 6. Tail match: any qualname ending with .target -- accept only if unique.
    suffix_matches: list[Node] = []
    for qn, nodes in index.by_qualname.items():
        if qn == target or qn.endswith("." + target):
            suffix_matches.extend(nodes)
    if len(suffix_matches) == 1:
        return suffix_matches[0]

    # 7. Bare-name match across the whole graph (only if globally unique).
    base = target.rsplit(".", 1)[-1]
    by_name = index.by_name.get(base, [])
    if len(by_name) == 1:
        return by_name[0]

    return None


def _build_import_bindings(
    edges: list[Edge], index: _Index
) -> dict[str, dict[str, str]]:
    """For each module node id, map import alias -> imported module qualname.

    Currently we only know the textual target_name (e.g. "models" or
    "./utils"), so the alias is the leaf segment.
    """
    bindings: dict[str, dict[str, str]] = defaultdict(dict)
    for edge in edges:
        if edge.kind != EdgeKind.IMPORTS:
            continue
        src_node = index.by_id.get(edge.src)
        if src_node is None or src_node.kind != NodeKind.MODULE:
            continue
        target = edge.metadata.get("target_name")
        if not isinstance(target, str) or not target:
            continue
        # Python parser may already produce absolute dotted qualnames for
        # relative imports (e.g. "pkg.models.Foo"). Only strip leading "./"
        # and "../" path noise, not bare leading dots that may be part of
        # a dotted qualname.
        normalized = target.replace("\\", "/")
        while normalized.startswith("./") or normalized.startswith("../"):
            normalized = normalized[2:] if normalized.startswith("./") \
                else normalized[3:]
        normalized = normalized.replace("/", ".")
        if not normalized:
            continue
        imported_name = edge.metadata.get("imported_name")
        if isinstance(imported_name, str) and imported_name:
            # Bind the alias used in the source file -> full qualname.
            bindings[src_node.id][imported_name] = normalized
            bindings[src_node.id][normalized] = normalized
        else:
            leaf = normalized.rsplit(".", 1)[-1]
            bindings[src_node.id][leaf] = normalized
            bindings[src_node.id][normalized] = normalized
    return bindings


def resolve_unresolved_edges(store: SQLiteGraphStore) -> ResolveStats:
    """Rewrite ``unresolved::*`` edges in-place, returning summary stats."""
    nodes = list(store.iter_nodes())
    edges = list(store.iter_edges())
    index = _Index(nodes)
    bindings = _build_import_bindings(edges, index)

    stats = ResolveStats()
    new_edges: list[Edge] = []
    deletions: list[tuple[str, str, EdgeKind]] = []

    for edge in edges:
        if not edge.dst.startswith("unresolved::"):
            continue
        if edge.kind not in _REFERENCE_KINDS:
            continue
        stats.inspected += 1
        meta_target = edge.metadata.get("target_name")
        target = (
            meta_target if isinstance(meta_target, str)
            else _strip_unresolved(edge.dst)
        )
        src_node = index.by_id.get(edge.src)

        # R3: ``self.X.tail`` may bind to multiple class types when the
        # enclosing class declares a union annotation or assigns the
        # attribute in branching ``__init__`` paths. We emit one edge per
        # candidate so the dead-code analyzer can see all reachable
        # implementations.
        multi = _try_multi_self_attr(
            target, src_node, edge.kind, index, bindings,
        )
        if multi:
            deletions.append((edge.src, edge.dst, edge.kind))
            for hit in multi:
                if hit.id == edge.src:
                    continue
                new_edges.append(
                    Edge(
                        src=edge.src,
                        dst=hit.id,
                        kind=edge.kind,
                        file=edge.file,
                        line=edge.line,
                        metadata={
                            **edge.metadata, "resolved_from": edge.dst,
                        },
                    )
                )
            stats.resolved += 1
            continue

        resolved = _resolve_target(target, src_node, index, bindings)
        if resolved is None or resolved.id == edge.src:
            stats.unresolved += 1
            # DF1: drop unresolved data-access edges so the graph never
            # carries ``unresolved::Model`` placeholders for SQL I/O.
            if edge.kind in _DROP_IF_UNRESOLVED:
                deletions.append((edge.src, edge.dst, edge.kind))
            continue
        # DF1 sanity: READS_FROM/WRITES_TO must resolve to a CLASS.
        if (
            edge.kind in _DROP_IF_UNRESOLVED
            and resolved.kind != NodeKind.CLASS
        ):
            stats.unresolved += 1
            deletions.append((edge.src, edge.dst, edge.kind))
            continue
        deletions.append((edge.src, edge.dst, edge.kind))
        new_edges.append(
            Edge(
                src=edge.src,
                dst=resolved.id,
                kind=edge.kind,
                file=edge.file,
                line=edge.line,
                metadata={**edge.metadata, "resolved_from": edge.dst},
            )
        )
        stats.resolved += 1

    for src, dst, kind in deletions:
        store.delete_edge(src, dst, kind)
    if new_edges:
        store.upsert_edges(new_edges)

    return stats
