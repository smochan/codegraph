"""Tests for TypeScript path-alias and index-file resolution.

Fixtures live under ``tests/fixtures/ts_path_aliases``, ``ts_jsconfig``,
and ``ts_index_file``. Each is built end-to-end via ``GraphBuilder`` so
the full resolver pipeline (including tsconfig loading) runs.
"""
from __future__ import annotations

import shutil
from pathlib import Path

from codegraph.graph.builder import GraphBuilder
from codegraph.graph.schema import EdgeKind, NodeKind
from codegraph.graph.store_sqlite import SQLiteGraphStore
from codegraph.resolve.tsconfig_paths import (
    TsPathMapping,
    load_ts_path_mapping,
    rewrite_alias,
)

FIXTURES = Path(__file__).parent / "fixtures"


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _build(tmp_path: Path, fixture: str) -> tuple[Path, SQLiteGraphStore]:
    """Copy *fixture* to a tmp repo and run a full build; return (repo, store)."""
    repo = tmp_path / "repo"
    shutil.copytree(FIXTURES / fixture, repo)
    store = SQLiteGraphStore(tmp_path / "graph.db")
    GraphBuilder(repo, store).build(incremental=False)
    return repo, store


def _count_unresolved(store: SQLiteGraphStore, kind: EdgeKind = EdgeKind.CALLS) -> int:
    return sum(
        1 for e in store.iter_edges(kind=kind)
        if e.dst.startswith("unresolved::")
    )


# ---------------------------------------------------------------------------
# Unit tests for tsconfig loader
# ---------------------------------------------------------------------------

def test_tolerant_parse_comments_and_trailing_commas(tmp_path: Path) -> None:
    """load_ts_path_mapping must handle // comments and trailing commas."""
    cfg = tmp_path / "tsconfig.json"
    cfg.write_text(
        '{\n'
        '  // this is a comment\n'
        '  "compilerOptions": {\n'
        '    "baseUrl": ".",\n'
        '    /* block comment */\n'
        '    "paths": {\n'
        '      "@/*": ["./src/*"],\n'  # trailing comma
        '    },\n'                      # trailing comma
        '    "strict": true,\n'         # trailing comma
        '  },\n'                        # trailing comma
        '}\n',
        encoding="utf-8",
    )
    mapping = load_ts_path_mapping(tmp_path)
    assert "@/*" in mapping.paths
    assert mapping.paths["@/*"] == ["./src/*"]


def test_jsconfig_loaded_when_no_tsconfig(tmp_path: Path) -> None:
    """load_ts_path_mapping falls back to jsconfig.json."""
    cfg = tmp_path / "jsconfig.json"
    cfg.write_text(
        '{"compilerOptions": {"paths": {"#/*": ["./lib/*"]}}}',
        encoding="utf-8",
    )
    mapping = load_ts_path_mapping(tmp_path)
    assert "#/*" in mapping.paths


def test_tsconfig_preferred_over_jsconfig(tmp_path: Path) -> None:
    """tsconfig.json is loaded before jsconfig.json."""
    (tmp_path / "tsconfig.json").write_text(
        '{"compilerOptions": {"paths": {"@/*": ["./src/*"]}}}',
        encoding="utf-8",
    )
    (tmp_path / "jsconfig.json").write_text(
        '{"compilerOptions": {"paths": {"@/*": ["./other/*"]}}}',
        encoding="utf-8",
    )
    mapping = load_ts_path_mapping(tmp_path)
    assert mapping.paths["@/*"] == ["./src/*"]


def test_no_config_returns_empty_mapping(tmp_path: Path) -> None:
    """Returns empty TsPathMapping when no tsconfig/jsconfig present."""
    mapping = load_ts_path_mapping(tmp_path)
    assert mapping.is_empty()


def test_rewrite_alias_basic() -> None:
    """rewrite_alias converts '@/lib/db' -> 'src.lib.db' for @/* -> ./src/*."""
    mapping = TsPathMapping(paths={"@/*": ["./src/*"]})
    result = rewrite_alias("@/lib/db", mapping, Path("/repo"))
    assert result == "src.lib.db", result


def test_rewrite_alias_no_match_returns_none() -> None:
    """rewrite_alias returns None when target doesn't match any pattern."""
    mapping = TsPathMapping(paths={"@/*": ["./src/*"]})
    result = rewrite_alias("./relative/path", mapping, Path("/repo"))
    assert result is None


def test_rewrite_alias_empty_mapping_returns_none() -> None:
    """rewrite_alias returns None for an empty mapping."""
    mapping = TsPathMapping()
    result = rewrite_alias("@/anything", mapping, Path("/repo"))
    assert result is None


# ---------------------------------------------------------------------------
# Integration: tsconfig path aliases (tsconfig.json with @/* -> ./src/*)
# ---------------------------------------------------------------------------

def test_tsconfig_alias_resolves_import_binding(tmp_path: Path) -> None:
    """'import { db } from \"@/lib/db\"' must bind db -> src.lib.db.db."""
    from codegraph.resolve.calls import _build_import_bindings, _Index
    from codegraph.resolve.tsconfig_paths import load_ts_path_mapping

    _repo, store = _build(tmp_path, "ts_path_aliases")
    repo = tmp_path / "repo"

    nodes = list(store.iter_nodes())
    edges = list(store.iter_edges())
    index = _Index(nodes)
    ts_mapping = load_ts_path_mapping(repo)
    bindings = _build_import_bindings(edges, index, ts_mapping, repo)

    # Find the app module
    app_module = next(
        (n for n in nodes
         if n.kind == NodeKind.MODULE and n.qualname.endswith("app")),
        None,
    )
    assert app_module is not None, "expected a module qualname ending with 'app'"

    module_bindings = bindings.get(app_module.id, {})
    assert "db" in module_bindings, (
        f"expected 'db' bound via @/lib/db alias; got {list(module_bindings)}"
    )
    bound = module_bindings["db"]
    assert "lib" in bound and "db" in bound, (
        f"binding should reference 'lib' and 'db', got {bound!r}"
    )


def test_tsconfig_alias_calls_edge_resolves(tmp_path: Path) -> None:
    """'db()' in app.ts must emit a resolved CALLS edge to src/lib/db.db."""
    _repo, store = _build(tmp_path, "ts_path_aliases")

    # Find the db function node
    db_funcs = [
        n for n in store.iter_nodes(kind=NodeKind.FUNCTION)
        if n.qualname.endswith(".db") or n.qualname == "db"
    ]
    assert db_funcs, "expected db function node in src/lib/db.ts"
    db_node = db_funcs[0]

    # Find main function in app.ts
    main_funcs = [
        n for n in store.iter_nodes(kind=NodeKind.FUNCTION)
        if n.qualname.endswith(".main") or n.qualname == "main"
    ]
    assert main_funcs, "expected main function in src/app.ts"
    main_node = main_funcs[0]

    # There should be a resolved CALLS edge from main to db
    calls = [
        e for e in store.iter_edges(src=main_node.id, kind=EdgeKind.CALLS)
        if e.dst == db_node.id
    ]
    assert calls, (
        f"expected CALLS edge from main -> db (resolved via @/lib/db alias); "
        f"main={main_node.qualname!r}, db={db_node.qualname!r}, "
        f"unresolved_calls={_count_unresolved(store)}"
    )


def test_tsconfig_alias_no_unresolved_for_in_repo_symbol(
    tmp_path: Path,
) -> None:
    """After alias resolution, no CALLS edge from main should be unresolved."""
    _repo, store = _build(tmp_path, "ts_path_aliases")

    main_funcs = [
        n for n in store.iter_nodes(kind=NodeKind.FUNCTION)
        if n.qualname.endswith(".main") or n.qualname == "main"
    ]
    assert main_funcs
    main_node = main_funcs[0]

    unresolved = [
        e for e in store.iter_edges(src=main_node.id, kind=EdgeKind.CALLS)
        if e.dst.startswith("unresolved::")
    ]
    assert not unresolved, (
        f"expected no unresolved CALLS from main; got {[e.dst for e in unresolved]}"
    )


# ---------------------------------------------------------------------------
# Integration: jsconfig.json variant
# ---------------------------------------------------------------------------

def test_jsconfig_alias_resolves(tmp_path: Path) -> None:
    """jsconfig.json with '#/*' path alias resolves greet() call."""
    _repo, store = _build(tmp_path, "ts_jsconfig")

    greet_funcs = [
        n for n in store.iter_nodes(kind=NodeKind.FUNCTION)
        if n.qualname.endswith(".greet") or n.qualname == "greet"
    ]
    assert greet_funcs, "expected greet function in src/utils/helper.ts"
    greet_node = greet_funcs[0]

    run_funcs = [
        n for n in store.iter_nodes(kind=NodeKind.FUNCTION)
        if n.qualname.endswith(".run") or n.qualname == "run"
    ]
    assert run_funcs, "expected run function in main.ts"
    run_node = run_funcs[0]

    calls = [
        e for e in store.iter_edges(src=run_node.id, kind=EdgeKind.CALLS)
        if e.dst == greet_node.id
    ]
    assert calls, (
        f"expected CALLS edge from run -> greet via jsconfig #/* alias; "
        f"run={run_node.qualname!r}, greet={greet_node.qualname!r}"
    )


# ---------------------------------------------------------------------------
# Integration: index-file resolution (./models -> models/index.ts)
# ---------------------------------------------------------------------------

def test_index_file_import_resolves_user_class(tmp_path: Path) -> None:
    """'import { User } from \"./models\"' resolves through models/index.ts.

    The TS parser emits an IMPORTS edge with target_name='./models.User'.
    The resolver must follow the index-file fallback to rewrite this to
    the resolved node src.models.index.User.
    """
    _repo, store = _build(tmp_path, "ts_index_file")

    user_classes = [
        n for n in store.iter_nodes(kind=NodeKind.CLASS)
        if n.qualname.endswith(".User") or n.qualname == "User"
    ]
    assert user_classes, "expected User class in src/models/index.ts"
    user_node = user_classes[0]

    # The service module should have an IMPORTS edge pointing to User
    service_mod = next(
        (n for n in store.iter_nodes(kind=NodeKind.MODULE)
         if n.qualname.endswith("service")),
        None,
    )
    assert service_mod is not None, "expected service module"

    # The IMPORTS edge from service to User should be resolved (not unresolved::)
    imports = [
        e for e in store.iter_edges(src=service_mod.id, kind=EdgeKind.IMPORTS)
        if e.dst == user_node.id
    ]
    assert imports, (
        f"expected IMPORTS edge from service -> User resolved via models/index.ts; "
        f"User={user_node.qualname!r}; "
        f"all imports: {[(e.dst, e.metadata) for e in store.iter_edges(src=service_mod.id, kind=EdgeKind.IMPORTS)]}"
    )


def test_index_file_import_binding_includes_user(tmp_path: Path) -> None:
    """_build_import_bindings must bind 'User' from './models' -> models.index.User."""
    from codegraph.resolve.calls import _build_import_bindings, _Index

    _repo, store = _build(tmp_path, "ts_index_file")

    nodes = list(store.iter_nodes())
    edges = list(store.iter_edges())
    index = _Index(nodes)
    bindings = _build_import_bindings(edges, index, None, None)

    # Find the service module
    service_mod = next(
        (n for n in nodes
         if n.kind == NodeKind.MODULE and n.qualname.endswith("service")),
        None,
    )
    assert service_mod is not None, "expected service module"

    module_bindings = bindings.get(service_mod.id, {})
    # User should be bound to models.index.User or similar
    assert "User" in module_bindings, (
        f"expected 'User' in bindings for service module; got {list(module_bindings)}"
    )


# ---------------------------------------------------------------------------
# Regression: no tsconfig -> behavior unchanged
# ---------------------------------------------------------------------------

def test_no_tsconfig_regression(tmp_path: Path) -> None:
    """Repos without tsconfig.json behave exactly as before."""
    repo = tmp_path / "repo"
    repo.mkdir()
    # Plain TS without any tsconfig
    (repo / "utils.ts").write_text(
        "export function add(a: number, b: number): number { return a + b; }\n"
    )
    (repo / "main.ts").write_text(
        "import { add } from './utils';\n"
        "export function main(): void { add(1, 2); }\n"
    )
    store = SQLiteGraphStore(tmp_path / "graph.db")
    GraphBuilder(repo, store).build(incremental=False)

    # add function should resolve
    add_funcs = [
        n for n in store.iter_nodes(kind=NodeKind.FUNCTION)
        if n.qualname.endswith(".add") or n.qualname == "add"
    ]
    assert add_funcs, "expected add function in utils.ts"
    add_node = add_funcs[0]

    main_funcs = [
        n for n in store.iter_nodes(kind=NodeKind.FUNCTION)
        if n.qualname.endswith(".main") or n.qualname == "main"
    ]
    assert main_funcs, "expected main function in main.ts"
    main_node = main_funcs[0]

    calls = [
        e for e in store.iter_edges(src=main_node.id, kind=EdgeKind.CALLS)
        if e.dst == add_node.id
    ]
    assert calls, (
        f"expected CALLS edge from main -> add (no tsconfig); "
        f"main={main_node.qualname!r}, add={add_node.qualname!r}"
    )
