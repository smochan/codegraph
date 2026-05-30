"""Tests for the `mcp:` block removal (v0.1.2 #7).

Pre-0.1.2 configs carried a vestigial ``mcp.enabled: false`` block that
no code path read. The field was removed in 0.1.2; the model is set to
silently ignore it so existing configs still load.
"""
from __future__ import annotations

from pathlib import Path

import yaml

from codegraph.config import CodegraphConfig, load_config, save_config


def test_old_config_with_mcp_block_still_loads(tmp_path: Path) -> None:
    cfg_path = tmp_path / ".codegraph.yml"
    cfg_path.write_text(yaml.dump({
        "version": 1,
        "register_mcp": True,
        "mcp": {"enabled": False},  # old vestigial field
    }))
    cfg = load_config(tmp_path)
    assert cfg.register_mcp is True
    # The vestigial field should NOT appear as an attribute.
    assert not hasattr(cfg, "mcp")


def test_fresh_config_does_not_emit_mcp_block(tmp_path: Path) -> None:
    cfg = CodegraphConfig()
    save_config(tmp_path, cfg)
    dumped = yaml.safe_load((tmp_path / ".codegraph.yml").read_text())
    assert "mcp" not in dumped
    assert "register_mcp" in dumped


def test_other_unknown_fields_also_ignored(tmp_path: Path) -> None:
    (tmp_path / ".codegraph.yml").write_text(yaml.dump({
        "version": 1,
        "future_field_we_havent_added_yet": "ok",
    }))
    cfg = load_config(tmp_path)
    assert cfg.version == 1
