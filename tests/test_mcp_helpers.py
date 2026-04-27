"""Direct unit tests for codegraph.mcp_server.server._node_df_metadata."""
from __future__ import annotations

from codegraph.mcp_server.server import _node_df_metadata


def test_returns_empty_when_no_metadata() -> None:
    assert _node_df_metadata({}) == {}


def test_returns_empty_when_metadata_none() -> None:
    assert _node_df_metadata({"metadata": None}) == {}


def test_returns_empty_when_metadata_not_dict() -> None:
    assert _node_df_metadata({"metadata": "bogus"}) == {}


def test_extracts_params() -> None:
    out = _node_df_metadata({"metadata": {"params": ["a", "b"]}})
    assert out == {"params": ["a", "b"]}


def test_extracts_returns() -> None:
    out = _node_df_metadata({"metadata": {"returns": "int"}})
    assert out == {"returns": "int"}


def test_extracts_role() -> None:
    out = _node_df_metadata({"metadata": {"role": "HANDLER"}})
    assert out == {"role": "HANDLER"}


def test_omits_role_when_none() -> None:
    out = _node_df_metadata({"metadata": {"role": None}})
    assert "role" not in out


def test_extracts_all_fields_together() -> None:
    out = _node_df_metadata(
        {"metadata": {"params": ["a"], "returns": "str", "role": "SERVICE"}}
    )
    assert out == {"params": ["a"], "returns": "str", "role": "SERVICE"}


def test_unrelated_keys_are_ignored() -> None:
    out = _node_df_metadata(
        {"metadata": {"params": ["a"], "extra": "ignored"}}
    )
    assert out == {"params": ["a"]}
