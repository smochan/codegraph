"""Tests for resolver R2 false-positive fixes.

Each pattern has its own fixture under ``tests/fixtures/resolver_r2/``.
The fixtures are copied into a temporary repo and built end-to-end (via
``GraphBuilder``) so the resolver runs and we can assert the correct
CALLS edges land in the store.
"""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from codegraph.graph.builder import GraphBuilder
from codegraph.graph.schema import EdgeKind, NodeKind
from codegraph.graph.store_sqlite import SQLiteGraphStore

FIXTURES = Path(__file__).parent / "fixtures" / "resolver_r2"


def _build(tmp_path: Path, fixture_name: str) -> SQLiteGraphStore:
    repo = tmp_path / "repo"
    repo.mkdir()
    shutil.copy(FIXTURES / fixture_name, repo / fixture_name)
    store = SQLiteGraphStore(tmp_path / "graph.db")
    GraphBuilder(repo, store).build(incremental=False)
    return store


def _find_one(store: SQLiteGraphStore, *, kind: NodeKind, suffix: str):
    nodes = [
        n for n in store.iter_nodes(kind=kind) if n.qualname.endswith(suffix)
    ]
    assert len(nodes) == 1, (
        f"expected one {kind.value} ending with {suffix!r}, got "
        f"{[n.qualname for n in nodes]}"
    )
    return nodes[0]


def _calls_to(store: SQLiteGraphStore, dst_id: str) -> list:
    return [
        e for e in store.iter_edges(kind=EdgeKind.CALLS) if e.dst == dst_id
    ]


def test_r2_same_file_constructor(tmp_path: Path) -> None:
    """Module-level ``Widget(...)`` calls should emit CALLS to the class."""
    store = _build(tmp_path, "same_file_ctor.py")
    widget = _find_one(store, kind=NodeKind.CLASS, suffix=".Widget")
    incoming = _calls_to(store, widget.id)
    assert incoming, (
        "expected at least one CALLS edge into Widget from the module-level "
        "list literal"
    )


def test_r2_nested_function_call(tmp_path: Path) -> None:
    """Calls inside nested ``def inner`` should attribute to ``inner``."""
    store = _build(tmp_path, "nested_call.py")
    helper = _find_one(store, kind=NodeKind.FUNCTION, suffix=".helper")
    inner = _find_one(store, kind=NodeKind.FUNCTION, suffix=".outer.inner")
    incoming = _calls_to(store, helper.id)
    srcs = {e.src for e in incoming}
    assert inner.id in srcs, (
        f"expected CALLS edge from nested 'inner' to 'helper'; got srcs="
        f"{srcs}"
    )


def test_r2_decorator_call(tmp_path: Path) -> None:
    """``@my_decorator(...)`` should emit a CALLS edge to my_decorator."""
    store = _build(tmp_path, "decorator_call.py")
    deco = _find_one(store, kind=NodeKind.FUNCTION, suffix=".my_decorator")
    incoming = _calls_to(store, deco.id)
    assert incoming, "expected CALLS edge from decorator usage to my_decorator"


def test_r2_class_annotation_self_chain(tmp_path: Path) -> None:
    """``self.svc.run()`` resolves via class-level annotation ``svc: Service``.
    """
    store = _build(tmp_path, "class_annotation.py")
    run = _find_one(store, kind=NodeKind.METHOD, suffix=".Service.run")
    go = _find_one(store, kind=NodeKind.METHOD, suffix=".Handler.go")
    incoming = _calls_to(store, run.id)
    srcs = {e.src for e in incoming}
    assert go.id in srcs, (
        f"expected CALLS edge from Handler.go to Service.run; got srcs={srcs}"
    )


def test_r2_instance_chain_method_call(tmp_path: Path) -> None:
    """``Builder().make()`` should emit a CALLS edge to Builder.make."""
    store = _build(tmp_path, "instance_chain.py")
    make = _find_one(store, kind=NodeKind.METHOD, suffix=".Builder.make")
    incoming = _calls_to(store, make.id)
    assert incoming, (
        "expected CALLS edge into Builder.make from Builder().make() chain"
    )


def test_ts_fresh_instance_both_edges(tmp_path: Path) -> None:
    """``new UserService().getUser(id)`` emits CALLS to both UserService
    (class, fresh_instance=True) and UserService.getUser (method).
    """
    store = _build(tmp_path, "ts_fresh_instance.ts")
    cls = _find_one(store, kind=NodeKind.CLASS, suffix=".UserService")
    method = _find_one(store, kind=NodeKind.METHOD, suffix=".UserService.getUser")
    method_calls = _calls_to(store, method.id)
    assert method_calls, (
        "expected CALLS edge into UserService.getUser from new UserService().getUser()"
    )
    class_calls = _calls_to(store, cls.id)
    fresh_calls = [e for e in class_calls if e.metadata.get("fresh_instance")]
    assert fresh_calls, (
        "expected CALLS edge with fresh_instance=True into UserService class"
    )


def test_ts_fresh_instance_factory_no_class_edge(tmp_path: Path) -> None:
    """``factory().run()`` must NOT produce a fresh_instance CALLS edge when
    ``factory`` is a plain function, not a class.
    """
    store = _build(tmp_path, "ts_fresh_instance_factory.ts")
    # factory is a FUNCTION; there should be no fresh_instance edge to it.
    factory_nodes = [
        n for n in store.iter_nodes(kind=NodeKind.FUNCTION)
        if n.qualname.endswith(".factory")
    ]
    assert factory_nodes, "expected a 'factory' function node in the graph"
    factory_id = factory_nodes[0].id
    calls_to_factory = _calls_to(store, factory_id)
    fresh_class_calls = [
        e for e in calls_to_factory if e.metadata.get("fresh_instance")
    ]
    assert not fresh_class_calls, (
        "factory() is a function, not a class — no fresh_instance edge expected"
    )


def test_ts_decorator_calls_edges(tmp_path: Path) -> None:
    """@Injectable() on a class and @Get(':id') on a method each emit a
    CALLS edge with decorator=True metadata.
    """
    store = _build(tmp_path, "ts_decorators.ts")
    injectable = _find_one(store, kind=NodeKind.FUNCTION, suffix=".Injectable")
    get_fn = _find_one(store, kind=NodeKind.FUNCTION, suffix=".Get")
    cls = _find_one(store, kind=NodeKind.CLASS, suffix=".UserController")
    method = _find_one(store, kind=NodeKind.METHOD, suffix=".UserController.getUser")

    # @Injectable() -> CALLS edge to Injectable from the class node.
    injectable_calls = [
        e for e in _calls_to(store, injectable.id)
        if e.src == cls.id and e.metadata.get("decorator")
    ]
    assert injectable_calls, (
        "expected decorator CALLS edge from UserController class to Injectable"
    )

    # @Get(':id') -> CALLS edge to Get from the method node.
    get_calls = [
        e for e in _calls_to(store, get_fn.id)
        if e.src == method.id and e.metadata.get("decorator")
    ]
    assert get_calls, (
        "expected decorator CALLS edge from getUser method to Get"
    )


def test_ts_decorator_unresolved_stays_unresolved(tmp_path: Path) -> None:
    """When the decorator is defined outside the repo, the CALLS edge stays
    unresolved (no crash, decorator metadata still present on the raw edge).
    """
    from codegraph.graph.store_sqlite import SQLiteGraphStore as _Store
    repo = tmp_path / "repo2"
    repo.mkdir()
    # Only the controller; decorators come from an external package.
    src = repo / "ctrl.ts"
    src.write_text(
        "import { Controller, Get } from '@nestjs/common';\n"
        "@Controller('users')\n"
        "export class UsersController {\n"
        "  @Get(':id')\n"
        "  getUser(id: string): string { return id; }\n"
        "}\n"
    )
    db = tmp_path / "g2.db"
    st = _Store(db)
    from codegraph.graph.builder import GraphBuilder
    GraphBuilder(repo, st).build(incremental=False)
    # Decorator edges should have been emitted with decorator=True but remain
    # unresolved (since nestjs is not in-repo). The graph must not crash.
    all_calls = list(st.iter_edges(kind=EdgeKind.CALLS))
    decorator_calls = [e for e in all_calls if e.metadata.get("decorator")]
    # There should be at least two decorator edges (Controller, Get).
    assert len(decorator_calls) >= 2, (
        f"expected >=2 unresolved decorator CALLS edges, got {len(decorator_calls)}"
    )


if __name__ == "__main__":  # pragma: no cover
    pytest.main([__file__, "-v"])
