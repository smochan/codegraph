"""Baseline graph snapshot management."""
from __future__ import annotations

import shutil
from pathlib import Path

import networkx as nx

from codegraph.graph.store_networkx import to_digraph
from codegraph.graph.store_sqlite import SQLiteGraphStore


def save_baseline(db_path: Path, baseline_path: Path) -> None:
    """Copy ``db_path`` to ``baseline_path`` (creating parents as needed)."""
    if not db_path.exists():
        raise FileNotFoundError(f"graph database not found: {db_path}")
    baseline_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(str(db_path), str(baseline_path))


def load_baseline(baseline_path: Path) -> nx.MultiDiGraph | None:
    """Load the baseline graph from ``baseline_path``.

    Returns ``None`` when the baseline file is missing.
    """
    if not baseline_path.exists():
        return None
    store = SQLiteGraphStore(baseline_path)
    try:
        return to_digraph(store)
    finally:
        store.close()
