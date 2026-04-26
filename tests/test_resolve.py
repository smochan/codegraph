"""Tests for the cross-file CALLS resolver."""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from codegraph.graph.builder import GraphBuilder
from codegraph.graph.schema import EdgeKind, NodeKind
from codegraph.graph.store_sqlite import SQLiteGraphStore
from codegraph.resolve import resolve_unresolved_edges

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def built_repo(tmp_path: Path) -> tuple[Path, SQLiteGraphStore]:
    repo = tmp_path / "repo"
    repo.mkdir()
    shutil.copytree(FIXTURES / "python_sample", repo / "pkg")
    store = SQLiteGraphStore(tmp_path / "graph.db")
    GraphBuilder(repo, store).build(incremental=False)
    return repo, store


def test_build_runs_resolver_and_reduces_unresolved(
    built_repo: tuple[Path, SQLiteGraphStore],
) -> None:
    _repo, store = built_repo
    # The builder already resolved on first pass; ensure most CALLS edges
    # to in-repo functions are no longer prefixed with unresolved::.
    calls = list(store.iter_edges(kind=EdgeKind.CALLS))
    resolved = [e for e in calls if not e.dst.startswith("unresolved::")]
    assert resolved, "expected at least one resolved CALLS edge"


def test_resolver_links_self_method_calls(
    built_repo: tuple[Path, SQLiteGraphStore],
) -> None:
    _repo, store = built_repo
    nodes = {n.qualname: n for n in store.iter_nodes(kind=NodeKind.METHOD)}
    fetch = next(
        (n for q, n in nodes.items() if q.endswith("Dog.fetch")), None
    )
    speak = next(
        (n for q, n in nodes.items() if q.endswith("Dog.speak")), None
    )
    assert fetch is not None
    assert speak is not None
    edges = [
        e for e in store.iter_edges(src=fetch.id, kind=EdgeKind.CALLS)
        if e.dst == speak.id
    ]
    assert edges, "Dog.fetch should resolve self.speak() to Dog.speak"


def test_resolver_links_imported_call(
    built_repo: tuple[Path, SQLiteGraphStore],
) -> None:
    _repo, store = built_repo
    funcs = {n.qualname: n for n in store.iter_nodes(kind=NodeKind.FUNCTION)}
    read_file = next(
        (n for q, n in funcs.items() if q.endswith("utils.read_file")), None
    )
    count_words = next(
        (n for q, n in funcs.items() if q.endswith("utils.count_words")), None
    )
    assert read_file is not None
    assert count_words is not None
    edges = [
        e for e in store.iter_edges(src=read_file.id, kind=EdgeKind.CALLS)
        if e.dst == count_words.id
    ]
    assert edges, "read_file should resolve count_words() to utils.count_words"


def test_resolver_idempotent(
    built_repo: tuple[Path, SQLiteGraphStore],
) -> None:
    _repo, store = built_repo
    before = store.count_unresolved_edges()
    rs = resolve_unresolved_edges(store)
    after = store.count_unresolved_edges()
    assert after == before
    assert rs.resolved == 0


def test_named_import_bindings_include_imported_names(tmp_path: Path) -> None:
    """`_build_import_bindings` must bind imported names (not just leaf
    module names) so `from models import Dog; Dog()` resolves via binding."""
    from codegraph.resolve.calls import _build_import_bindings, _Index

    repo = tmp_path / "repo"
    repo.mkdir()
    shutil.copytree(FIXTURES / "python_sample", repo / "pkg")
    store = SQLiteGraphStore(tmp_path / "graph.db")
    GraphBuilder(repo, store).build(incremental=False)

    nodes = list(store.iter_nodes())
    edges = list(store.iter_edges())
    index = _Index(nodes)
    bindings = _build_import_bindings(edges, index)

    # Find the test_models module (which does `from models import Cat, Dog`).
    test_module = next(
        n for n in nodes
        if n.kind == NodeKind.MODULE and n.qualname.endswith("test_models")
    )
    module_bindings = bindings.get(test_module.id, {})
    assert "Dog" in module_bindings, (
        f"expected 'Dog' bound from named import, got bindings keys "
        f"{list(module_bindings)}"
    )
    assert module_bindings["Dog"].endswith(".models.Dog") or \
        module_bindings["Dog"] == "models.Dog", module_bindings["Dog"]


def test_resolver_resolves_named_import_call(tmp_path: Path) -> None:
    """`from models import Dog` then `Dog(...)` resolves to pkg.models.Dog."""
    repo = tmp_path / "repo"
    repo.mkdir()
    shutil.copytree(FIXTURES / "python_sample", repo / "pkg")
    store = SQLiteGraphStore(tmp_path / "graph.db")
    GraphBuilder(repo, store).build(incremental=False)

    classes = {n.qualname: n for n in store.iter_nodes(kind=NodeKind.CLASS)}
    dog = next((n for q, n in classes.items() if q.endswith("models.Dog")), None)
    assert dog is not None

    funcs = {n.qualname: n for n in store.iter_nodes(kind=NodeKind.FUNCTION)}
    create_animal = next(
        (n for q, n in funcs.items() if q.endswith("utils.create_animal")),
        None,
    )
    assert create_animal is not None
    edges = [
        e for e in store.iter_edges(src=create_animal.id, kind=EdgeKind.CALLS)
        if e.dst == dog.id
    ]
    assert edges, "create_animal should resolve Dog(...) to pkg.models.Dog"


def test_relative_import_bindings_resolve_to_absolute(tmp_path: Path) -> None:
    """`from .models import Foo` in pkg/service.py must bind 'Foo' to the
    absolute qualname `pkg.models.Foo`, not a stripped './'-prefix."""
    from codegraph.resolve.calls import _build_import_bindings, _Index

    repo = tmp_path / "repo"
    repo.mkdir()
    shutil.copytree(FIXTURES / "py_relative_import" / "pkg", repo / "pkg")
    store = SQLiteGraphStore(tmp_path / "graph.db")
    GraphBuilder(repo, store).build(incremental=False)

    nodes = list(store.iter_nodes())
    edges = list(store.iter_edges())
    index = _Index(nodes)
    bindings = _build_import_bindings(edges, index)

    service_mod = next(
        n for n in nodes
        if n.kind == NodeKind.MODULE and n.qualname.endswith("pkg.service")
    )
    module_bindings = bindings.get(service_mod.id, {})
    assert "Foo" in module_bindings, (
        f"expected 'Foo' bound from relative named import, got {module_bindings}"
    )
    assert module_bindings["Foo"] == "pkg.models.Foo", module_bindings["Foo"]


def test_resolver_resolves_relative_import(tmp_path: Path) -> None:
    """`from .models import Foo` in pkg/service.py resolves Foo() to
    pkg.models.Foo."""
    repo = tmp_path / "repo"
    repo.mkdir()
    shutil.copytree(FIXTURES / "py_relative_import" / "pkg", repo / "pkg")
    store = SQLiteGraphStore(tmp_path / "graph.db")
    GraphBuilder(repo, store).build(incremental=False)

    classes = {n.qualname: n for n in store.iter_nodes(kind=NodeKind.CLASS)}
    foo = next((n for q, n in classes.items() if q.endswith("models.Foo")), None)
    assert foo is not None

    funcs = {n.qualname: n for n in store.iter_nodes(kind=NodeKind.FUNCTION)}
    make_foo = next(
        (n for q, n in funcs.items() if q.endswith("service.make_foo")), None
    )
    assert make_foo is not None
    edges = [
        e for e in store.iter_edges(src=make_foo.id, kind=EdgeKind.CALLS)
        if e.dst == foo.id
    ]
    assert edges, "make_foo should resolve Foo() to pkg.models.Foo via relative import"


def test_resolver_self_dotted_chain_does_not_crash(tmp_path: Path) -> None:
    """`self.foo.bar()` should not look up bogus 'ClassName.foo.bar' qualname.

    With the heuristic-1 fix, the resolver should fall through to subsequent
    heuristics and either resolve to the first segment or stay unresolved
    cleanly — never silently swallow into a non-existent qualname.
    """
    src_dir = tmp_path / "repo"
    src_dir.mkdir()
    (src_dir / "mod.py").write_text(
        "class Holder:\n"
        "    def m(self) -> str:\n"
        "        return self.foo.bar()\n"
        "\n"
        "    def foo_helper(self) -> str:\n"
        "        return ''\n"
    )
    store = SQLiteGraphStore(tmp_path / "graph.db")
    GraphBuilder(src_dir, store).build(incremental=False)

    methods = {n.qualname: n for n in store.iter_nodes(kind=NodeKind.METHOD)}
    m = next((n for q, n in methods.items() if q.endswith("Holder.m")), None)
    assert m is not None
    # The CALLS edge must NOT resolve to a phantom 'Holder.foo.bar' node.
    edges = list(store.iter_edges(src=m.id, kind=EdgeKind.CALLS))
    for e in edges:
        if not e.dst.startswith("unresolved::"):
            target = store.get_node(e.dst)
            assert target is not None, (
                f"resolved CALLS edge from Holder.m points to non-existent "
                f"node {e.dst}"
            )
            assert "foo.bar" not in target.qualname


def test_delete_edge_removes_only_target(tmp_path: Path) -> None:
    from codegraph.graph.schema import Edge

    store = SQLiteGraphStore(tmp_path / "g.db")
    edges = [
        Edge(src="a", dst="b", kind=EdgeKind.CALLS),
        Edge(src="a", dst="c", kind=EdgeKind.CALLS),
    ]
    store.upsert_edges(edges)
    store.delete_edge("a", "b", EdgeKind.CALLS)
    remaining = list(store.iter_edges(src="a"))
    assert len(remaining) == 1
    assert remaining[0].dst == "c"
