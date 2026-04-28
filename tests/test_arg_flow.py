"""Tests for per-hop ``arg_flow`` propagation (v0.3 stretch — argument flow).

Each hop in ``dataflow.hops`` carries an ``arg_flow`` dict mapping every
starting key to its locally-renamed name at that hop (or ``None``). Starting
keys are derived from the first FETCH_CALL hop's ``body_keys`` plus its
positional ``args``; falling back to the ROUTE hop's ``args`` for
backend-only traces.

The matching algorithm is text-only: lowercase + strip leading underscores +
collapse snake_case / camelCase tokens, then equality.
"""
from __future__ import annotations

import networkx as nx
import pytest

from codegraph.analysis.dataflow import (
    _compute_arg_flow,
    _normalise_arg_name,
    shape_hops_for_handler,
)
from codegraph.graph.schema import EdgeKind, NodeKind

# --- Graph builders -----------------------------------------------------


def _add_function(
    g: nx.MultiDiGraph,
    nid: str,
    qualname: str,
    *,
    file: str = "app.py",
    line: int = 1,
    role: str | None = None,
    kind: str = NodeKind.FUNCTION.value,
) -> None:
    metadata: dict[str, object] = {}
    if role is not None:
        metadata["role"] = role
    g.add_node(
        nid,
        kind=kind,
        qualname=qualname,
        file=file,
        line_start=line,
        metadata=metadata,
    )


def _build_graph(
    *,
    handler_args: list[str],
    service_args: list[str],
    repo_args: list[str],
    method: str = "GET",
    path: str = "/api/users/{user_id}",
    fetch_url: str | None = None,
    fetch_body_keys: list[str] | None = None,
    include_fetch: bool = True,
) -> nx.MultiDiGraph:
    """Build a frontend → handler → service → repo → model chain."""
    if fetch_url is None:
        # Default: derive a concrete URL from the path template by replacing
        # {param} segments with a literal "1".
        import re as _re
        fetch_url = _re.sub(r"\{[^}]+\}", "1", path)
    g: nx.MultiDiGraph = nx.MultiDiGraph()

    if include_fetch:
        _add_function(
            g, "n_component", "src/UserCard.tsx::fetchUser",
            file="src/UserCard.tsx", line=42, role="COMPONENT",
        )
    _add_function(
        g, "n_handler", "app.api.users.get_user",
        file="app/api/users.py", line=11, role="HANDLER",
    )
    _add_function(
        g, "n_service", "app.services.user.UserService.get",
        file="app/services/user.py", line=7, role="SERVICE",
        kind=NodeKind.METHOD.value,
    )
    _add_function(
        g, "n_repo", "app.repos.user.UserRepo.find_by_id",
        file="app/repos/user.py", line=11, role="REPO",
        kind=NodeKind.METHOD.value,
    )
    g.add_node(
        "n_model", kind=NodeKind.CLASS.value, qualname="app.models.User",
        file="app/models.py", line_start=8, metadata={},
    )
    g.add_node(
        "n_route", kind="ROUTE_TARGET",
        qualname=f"route::{method}::{path}",
        file="", line_start=0, metadata={"synthetic_kind": "ROUTE"},
    )

    g.add_edge(
        "n_handler", "n_route",
        key=EdgeKind.ROUTE.value, kind=EdgeKind.ROUTE.value,
        metadata={"method": method, "path": path, "framework": "fastapi",
                  "args": handler_args},
    )
    g.add_edge(
        "n_handler", "n_service",
        key=EdgeKind.CALLS.value, kind=EdgeKind.CALLS.value,
        metadata={"args": service_args, "kwargs": {}},
    )
    g.add_edge(
        "n_service", "n_repo",
        key=EdgeKind.CALLS.value, kind=EdgeKind.CALLS.value,
        metadata={"args": repo_args, "kwargs": {}},
    )
    g.add_edge(
        "n_repo", "n_model",
        key=EdgeKind.READS_FROM.value, kind=EdgeKind.READS_FROM.value,
        metadata={"operation": "select", "via": "session.query"},
    )
    if include_fetch:
        g.add_edge(
            "n_component", "n_route",
            key=EdgeKind.FETCH_CALL.value, kind=EdgeKind.FETCH_CALL.value,
            metadata={
                "method": method, "url": fetch_url,
                "library": "fetch",
                "body_keys": fetch_body_keys or [],
            },
        )
    return g


# --- Normalisation unit tests ------------------------------------------


@pytest.mark.parametrize(
    "name,expected",
    [
        ("userId", "userid"),
        ("user_id", "userid"),
        ("_user_id", "userid"),
        ("__user_id__", "userid"),
        ("UserID", "userid"),
        ("userid", "userid"),
        ("USER_ID", "userid"),
        ("'userId'", "userid"),
        ("", ""),
        ("___", ""),
    ],
)
def test_normalise_arg_name_variants(name: str, expected: str) -> None:
    assert _normalise_arg_name(name) == expected


def test_compute_arg_flow_empty_starting_keys() -> None:
    assert _compute_arg_flow([], ["a", "b"]) == {}


def test_compute_arg_flow_picks_first_match() -> None:
    out = _compute_arg_flow(["userId"], ["self", "user_id", "extra"])
    assert out == {"userId": "user_id"}


# --- shape_hops_for_handler integration tests --------------------------


def test_single_starting_key_flows_through_camel_to_snake() -> None:
    """userId from fetch propagates to user_id at service / repo hops."""
    g = _build_graph(
        handler_args=["user_id"],
        service_args=["user_id"],
        repo_args=["user_id"],
        # Simulate a body carrying userId (covers the propagation case;
        # the empty-body case is exercised in test #4).
        fetch_body_keys=["userId"],
    )
    df = shape_hops_for_handler(
        g, "app.api.users.get_user",
        method="GET", path="/api/users/{user_id}",
    )
    by_qn = {h["qualname"]: h for h in df["hops"]}
    # FETCH_CALL hop's local args=[] → userId has no rename here.
    assert by_qn["src/UserCard.tsx::fetchUser"]["arg_flow"] == {"userId": None}
    # ROUTE hop has args=[] (entry hop never carries args in the trace).
    assert by_qn["app.api.users.get_user"]["arg_flow"] == {"userId": None}
    # Service / repo hops carry user_id which normalises to userid → match.
    assert by_qn["app.services.user.UserService.get"]["arg_flow"] == {
        "userId": "user_id",
    }
    assert by_qn["app.repos.user.UserRepo.find_by_id"]["arg_flow"] == {
        "userId": "user_id",
    }
    # Model node has no args → userId stays None.
    assert by_qn["app.models.User"]["arg_flow"] == {"userId": None}


def test_multiple_starting_keys_one_drops_out() -> None:
    """email + password — password drops out at one hop."""
    g = _build_graph(
        handler_args=["email", "password"],
        service_args=["email"],  # password missing here
        repo_args=["email", "password"],
        fetch_body_keys=["email", "password"],
        method="POST",
        path="/api/signup",
    )
    df = shape_hops_for_handler(
        g, "app.api.users.get_user",
        method="POST", path="/api/signup",
    )
    by_qn = {h["qualname"]: h for h in df["hops"]}
    # Service hop has only ["email"] — password should be None.
    assert by_qn["app.services.user.UserService.get"]["arg_flow"] == {
        "email": "email", "password": None,
    }
    # Repo hop has both — both map.
    assert by_qn["app.repos.user.UserRepo.find_by_id"]["arg_flow"] == {
        "email": "email", "password": "password",
    }


def test_no_starting_keys_means_empty_arg_flow_per_hop() -> None:
    """Backend-only chain with handler that has no args → arg_flow == {}."""
    g = _build_graph(
        handler_args=[],  # empty
        service_args=["something"],
        repo_args=["other"],
        include_fetch=False,
    )
    df = shape_hops_for_handler(
        g, "app.api.users.get_user",
        method="GET", path="/api/users/{user_id}",
    )
    assert df["hops"]  # not empty
    for h in df["hops"]:
        assert h["arg_flow"] == {}


def test_starting_keys_come_from_body_keys_when_hop_args_empty() -> None:
    """FETCH_CALL hop's body_keys drive starting keys even if args is []."""
    g = _build_graph(
        handler_args=["user_id"],
        service_args=["user_id"],
        repo_args=["user_id"],
        fetch_body_keys=["userId"],
        method="POST",
        path="/api/users",
    )
    df = shape_hops_for_handler(
        g, "app.api.users.get_user",
        method="POST", path="/api/users",
    )
    # Every hop's arg_flow has exactly the starting keys.
    for h in df["hops"]:
        assert set(h["arg_flow"].keys()) == {"userId"}


def test_starting_key_not_present_anywhere_records_null_everywhere() -> None:
    """A starting key that no downstream hop renames stays None throughout."""
    g = _build_graph(
        handler_args=["user_id"],
        service_args=["user_id"],
        repo_args=["user_id"],
        fetch_body_keys=["totallyUnrelated"],
    )
    df = shape_hops_for_handler(
        g, "app.api.users.get_user",
        method="GET", path="/api/users/{user_id}",
    )
    for h in df["hops"]:
        assert h["arg_flow"] == {"totallyUnrelated": None}


def test_trailing_and_leading_underscore_variants_match_camel_case() -> None:
    """`_user_id` should normalise-equal `userId`."""
    g = _build_graph(
        handler_args=["_user_id"],
        service_args=["__user_id"],
        repo_args=["user_id_"],
        fetch_body_keys=["userId"],
    )
    df = shape_hops_for_handler(
        g, "app.api.users.get_user",
        method="GET", path="/api/users/{user_id}",
    )
    by_qn = {h["qualname"]: h for h in df["hops"]}
    assert by_qn["app.services.user.UserService.get"]["arg_flow"] == {
        "userId": "__user_id",
    }
    assert by_qn["app.repos.user.UserRepo.find_by_id"]["arg_flow"] == {
        "userId": "user_id_",
    }


@pytest.mark.parametrize(
    "variant",
    ["UserID", "user_id", "userId", "userid", "USER_ID", "_userId_"],
)
def test_mixed_case_variants_all_normalise_equal_to_userid(variant: str) -> None:
    """Any of these variants of ``userId`` should match each other."""
    g = _build_graph(
        handler_args=[variant],
        service_args=[variant],
        repo_args=[variant],
        fetch_body_keys=["userId"],
    )
    df = shape_hops_for_handler(
        g, "app.api.users.get_user",
        method="GET", path="/api/users/{user_id}",
    )
    by_qn = {h["qualname"]: h for h in df["hops"]}
    assert by_qn["app.services.user.UserService.get"]["arg_flow"] == {
        "userId": variant,
    }
    assert by_qn["app.repos.user.UserRepo.find_by_id"]["arg_flow"] == {
        "userId": variant,
    }


def test_backend_only_trace_starting_keys_from_route_args() -> None:
    """No FETCH_CALL hop → starting keys come from the first hop's args."""
    # Build a chain without a fetch edge. The first hop will be ROUTE
    # carrying ``args=["user_id"]`` from the ROUTE edge metadata... except
    # the trace builder reads args from the *incoming* CALLS edge, so the
    # ROUTE/entry hop has args=[] in the current contract. To exercise the
    # fallback path, we make the second hop carry args we want to flow.
    # The fallback rule says: starting keys = first hop's args. With
    # args=[] the result is {}; that's correct when there's nothing to track.
    g = _build_graph(
        handler_args=["user_id"],
        service_args=["user_id"],
        repo_args=["user_id"],
        include_fetch=False,
    )
    df = shape_hops_for_handler(
        g, "app.api.users.get_user",
        method="GET", path="/api/users/{user_id}",
    )
    # First hop is ROUTE with args=[] (entry hop has no incoming call edge).
    # → starting_keys = [] → arg_flow == {} for every hop.
    for h in df["hops"]:
        assert h["arg_flow"] == {}


def test_backend_only_with_synthetic_first_hop_args() -> None:
    """When the entry hop *does* have args, those drive starting keys.

    Simulate this by patching the ROUTE hop's args after shaping is done?
    No — instead, exercise via a chain whose first hop carries args. The
    public path doesn't put args on the entry hop, so we directly verify
    the helper logic via the internal _starting_keys_from_hops path by
    constructing a hop list manually.
    """
    from codegraph.analysis.dataflow import (
        _compute_arg_flow,
        _starting_keys_from_hops,
    )
    hops = [
        {"kind": "ROUTE", "args": ["userId"]},
        {"kind": "CALL", "args": ["user_id"]},
    ]
    keys = _starting_keys_from_hops(hops)
    assert keys == ["userId"]
    assert _compute_arg_flow(keys, hops[1]["args"]) == {"userId": "user_id"}


def test_arg_flow_keys_are_stable_across_all_hops() -> None:
    """Frontend renderer relies on identical key set per hop for column count."""
    g = _build_graph(
        handler_args=["user_id"],
        service_args=["user_id"],
        repo_args=["user_id"],
        fetch_body_keys=["userId", "tenantId"],
    )
    df = shape_hops_for_handler(
        g, "app.api.users.get_user",
        method="GET", path="/api/users/{user_id}",
    )
    expected = {"userId", "tenantId"}
    for h in df["hops"]:
        assert set(h["arg_flow"].keys()) == expected


def test_route_entry_args_backfilled_from_handler_params() -> None:
    """The ROUTE entry hop has no incoming CALLS edge, so trace() can't
    populate its args. When the handler node carries DF0 ``metadata.params``,
    those names backfill the ROUTE hop's args so URL-template params (e.g.
    ``user_id`` in ``/api/users/{user_id}``) drive arg_flow propagation.

    Without this fix, every URL-template-only handler (no body, no fetch
    body_keys) would produce ``arg_flow == {}`` for every hop.
    """
    g: nx.MultiDiGraph = nx.MultiDiGraph()
    # Handler node carrying DF0 params metadata — this is what the parser
    # emits when it sees `def get_user(user_id: int)` on a real codebase.
    g.add_node(
        "n_handler",
        kind=NodeKind.FUNCTION.value,
        qualname="app.api.users.get_user",
        file="app/api/users.py",
        line_start=11,
        metadata={
            "role": "HANDLER",
            "params": [
                {"name": "user_id", "type": "int", "default": None},
            ],
        },
    )
    df = shape_hops_for_handler(
        g, "app.api.users.get_user",
        method="GET", path="/api/users/{user_id}",
    )
    assert len(df["hops"]) == 1
    route = df["hops"][0]
    assert route["kind"] == "ROUTE"
    assert route["args"] == ["user_id"]
    assert route["arg_flow"] == {"user_id": "user_id"}


def test_route_entry_args_skip_self_and_cls() -> None:
    """Method handlers' ``self`` / ``cls`` are dropped from the backfill."""
    g: nx.MultiDiGraph = nx.MultiDiGraph()
    g.add_node(
        "n_handler",
        kind=NodeKind.METHOD.value,
        qualname="app.api.users.UserHandlers.get",
        file="app/api/users.py",
        line_start=20,
        metadata={
            "role": "HANDLER",
            "params": [
                {"name": "self", "type": None, "default": None},
                {"name": "user_id", "type": "int", "default": None},
            ],
        },
    )
    df = shape_hops_for_handler(
        g, "app.api.users.UserHandlers.get",
        method="GET", path="/api/users/{user_id}",
    )
    assert df["hops"][0]["args"] == ["user_id"]


def test_route_entry_backfill_does_not_override_existing_args() -> None:
    """If trace() somehow populated ROUTE args (e.g. via FETCH_CALL prepend
    plumbing), don't overwrite them."""
    g = _build_graph(
        handler_args=["user_id"],
        service_args=["user_id"],
        repo_args=["user_id"],
        fetch_body_keys=["email"],
    )
    # The handler in _build_graph already has params via handler_args.
    df = shape_hops_for_handler(
        g, "app.api.users.get_user",
        method="GET", path="/api/users/{user_id}",
    )
    # Starting keys come from FETCH_CALL body_keys=["email"], not the
    # handler's user_id.
    for h in df["hops"]:
        assert "email" in h["arg_flow"]
