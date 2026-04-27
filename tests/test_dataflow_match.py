"""DF3 — URL stitcher tests for codegraph.analysis.dataflow.match_route."""
from __future__ import annotations

import networkx as nx

from codegraph.analysis.dataflow import match_route
from codegraph.graph.schema import EdgeKind, NodeKind


def _graph_with_route(
    handler_qn: str,
    method: str,
    path: str,
    *,
    handler_params: list[dict[str, str | None]] | None = None,
) -> nx.MultiDiGraph:
    """Build a minimal graph with one HANDLER + one ROUTE edge."""
    g: nx.MultiDiGraph = nx.MultiDiGraph()
    handler_id = f"handler::{handler_qn}"
    g.add_node(
        handler_id,
        qualname=handler_qn,
        name=handler_qn.rsplit(".", 1)[-1],
        kind=NodeKind.FUNCTION.value,
        file=f"app/{handler_qn.split('.')[-1]}.py",
        line_start=1,
        metadata={
            "role": "HANDLER",
            "params": handler_params or [],
        },
    )
    route_id = f"route::{method.upper()}::{path}"
    g.add_node(
        route_id,
        qualname=route_id,
        name=f"{method.upper()} {path}",
        kind=NodeKind.VARIABLE.value,
        metadata={"synthetic_kind": "ROUTE"},
    )
    g.add_edge(
        handler_id,
        route_id,
        key=EdgeKind.ROUTE.value,
        kind=EdgeKind.ROUTE.value,
        metadata={"method": method.upper(), "path": path, "framework": "fastapi"},
    )
    return g


def _add_route(
    g: nx.MultiDiGraph,
    handler_qn: str,
    method: str,
    path: str,
    *,
    handler_params: list[dict[str, str | None]] | None = None,
) -> None:
    handler_id = f"handler::{handler_qn}"
    g.add_node(
        handler_id,
        qualname=handler_qn,
        name=handler_qn.rsplit(".", 1)[-1],
        kind=NodeKind.FUNCTION.value,
        file=f"app/{handler_qn.split('.')[-1]}.py",
        line_start=1,
        metadata={"role": "HANDLER", "params": handler_params or []},
    )
    route_id = f"route::{method.upper()}::{path}"
    g.add_node(
        route_id,
        qualname=route_id,
        kind=NodeKind.VARIABLE.value,
        metadata={"synthetic_kind": "ROUTE"},
    )
    g.add_edge(
        handler_id,
        route_id,
        key=EdgeKind.ROUTE.value,
        kind=EdgeKind.ROUTE.value,
        metadata={"method": method.upper(), "path": path, "framework": "fastapi"},
    )


# ---- Test 1: exact literal match ----
def test_exact_literal_match_confidence_1() -> None:
    g = _graph_with_route("api.get_health", "GET", "/api/health")
    out = match_route(g, "/api/health", "GET")
    assert out is not None
    assert out[0] == "api.get_health"
    assert out[1] == 1.0


# ---- Test 2: placeholder in route, literal in fetch ----
def test_route_placeholder_vs_literal_fetch_confidence_0_9() -> None:
    g = _graph_with_route("api.get_user", "GET", "/api/users/{id}")
    out = match_route(g, "/api/users/42", "GET")
    assert out is not None
    assert out[0] == "api.get_user"
    assert out[1] == 0.9


# ---- Test 3: template literal placeholder ${id} ----
def test_template_literal_placeholder_matches() -> None:
    g = _graph_with_route("api.get_user", "GET", "/api/users/{id}")
    out = match_route(g, "/api/users/${id}", "GET")
    assert out is not None
    assert out[0] == "api.get_user"
    assert out[1] == 0.9


# ---- Test 4: Express-style :id placeholder ----
def test_express_style_colon_placeholder_matches() -> None:
    g = _graph_with_route("api.get_user", "GET", "/api/users/{id}")
    out = match_route(g, "/api/users/:id", "GET")
    assert out is not None
    assert out[0] == "api.get_user"


# ---- Test 5: method mismatch ----
def test_method_mismatch_returns_none() -> None:
    g = _graph_with_route("api.create_user", "POST", "/api/users")
    out = match_route(g, "/api/users", "GET")
    assert out is None


# ---- Test 6: same path two methods, only matching method picked ----
def test_two_methods_same_path_picks_matching() -> None:
    g = _graph_with_route("api.get_users", "GET", "/api/users")
    _add_route(g, "api.create_user", "POST", "/api/users")
    out = match_route(g, "/api/users", "POST")
    assert out is not None
    assert out[0] == "api.create_user"


# ---- Test 7: more specific path wins tie ----
def test_more_specific_path_wins_tie() -> None:
    g = _graph_with_route("api.get_me", "GET", "/users/me")
    _add_route(g, "api.get_user_by_id", "GET", "/users/{id}")
    # Fetching /users/me — both routes' normalised forms could match
    # the literal "me" segment (it's not numeric/{}/$/:). So /users/me
    # exact-matches the literal route; /users/{id} also normalises but
    # at lower priority due to specificity.
    out = match_route(g, "/users/me", "GET")
    assert out is not None
    assert out[0] == "api.get_me"


# ---- Test 8: no routes in graph ----
def test_empty_graph_returns_none() -> None:
    g: nx.MultiDiGraph = nx.MultiDiGraph()
    out = match_route(g, "/api/users", "GET")
    assert out is None


# ---- Test 9: body-key overlap bumps confidence (placeholder path) ----
def test_body_keys_overlap_bumps_confidence() -> None:
    # Use a placeholder route so the base score is 0.9 and can grow.
    g = _graph_with_route(
        "api.update_user",
        "PUT",
        "/api/users/{id}",
        handler_params=[
            {"name": "id", "type": "int", "default": None},
            {"name": "email", "type": "str", "default": None},
        ],
    )
    out_no_keys = match_route(g, "/api/users/42", "PUT")
    assert out_no_keys is not None
    base = out_no_keys[1]

    out_with_keys = match_route(
        g, "/api/users/42", "PUT", body_keys=["email"]
    )
    assert out_with_keys is not None
    assert out_with_keys[1] > base
    assert out_with_keys[1] <= 1.0


# ---- Test 10: body-keys without overlap don't bump ----
def test_body_keys_no_overlap_no_bump() -> None:
    g = _graph_with_route(
        "api.create_user",
        "POST",
        "/api/users",
        handler_params=[
            {"name": "email", "type": "str", "default": None},
        ],
    )
    out_no_keys = match_route(g, "/api/users", "POST")
    out_with_unrelated = match_route(
        g, "/api/users", "POST", body_keys=["foo", "bar"]
    )
    assert out_no_keys is not None
    assert out_with_unrelated is not None
    assert out_no_keys[1] == out_with_unrelated[1]


# ---- Test 11: multiple placeholders in path ----
def test_multiple_placeholders_match() -> None:
    g = _graph_with_route(
        "api.get_user_post", "GET", "/users/{uid}/posts/{pid}"
    )
    out = match_route(g, "/users/42/posts/7", "GET")
    assert out is not None
    assert out[0] == "api.get_user_post"
    assert out[1] == 0.9


# ---- Test 12: trailing slash differences match ----
def test_trailing_slash_normalised() -> None:
    g = _graph_with_route("api.get_users", "GET", "/api/users")
    out_with_slash = match_route(g, "/api/users/", "GET")
    out_without = match_route(g, "/api/users", "GET")
    assert out_with_slash is not None
    assert out_without is not None
    assert out_with_slash[0] == out_without[0]


# ---- Test 13: case-insensitive method ----
def test_case_insensitive_method() -> None:
    g = _graph_with_route("api.get_users", "GET", "/api/users")
    out = match_route(g, "/api/users", "get")
    assert out is not None
    assert out[0] == "api.get_users"


# ---- Test 14: query string is stripped ----
def test_query_string_stripped() -> None:
    g = _graph_with_route("api.search", "GET", "/api/search")
    out = match_route(g, "/api/search?q=hello&limit=10", "GET")
    assert out is not None
    assert out[0] == "api.search"


# ---- Test 15: fragment is stripped ----
def test_fragment_stripped() -> None:
    g = _graph_with_route("api.get_doc", "GET", "/api/docs")
    out = match_route(g, "/api/docs#section-1", "GET")
    assert out is not None
    assert out[0] == "api.get_doc"


# ---- Test 16: prefix-only fuzzy match returns 0.5 ----
def test_prefix_only_match_returns_0_5() -> None:
    g = _graph_with_route("api.users_root", "GET", "/api/users")
    out = match_route(g, "/api/users/42/posts", "GET")
    assert out is not None
    assert out[0] == "api.users_root"
    assert out[1] == 0.5


# ---- Test 17: completely different path returns None ----
def test_unrelated_path_returns_none() -> None:
    g = _graph_with_route("api.users", "GET", "/api/users")
    out = match_route(g, "/api/orders", "GET")
    assert out is None
