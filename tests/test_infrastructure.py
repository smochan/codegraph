"""Tests for the infrastructure-component detection pass."""
from __future__ import annotations

from pathlib import Path

import networkx as nx
import pytest

from codegraph.analysis.infrastructure import detect_infrastructure
from codegraph.analysis.roles import classify_roles
from codegraph.graph.builder import GraphBuilder
from codegraph.graph.store_networkx import to_digraph
from codegraph.graph.store_sqlite import SQLiteGraphStore

FIXTURES = Path(__file__).parent / "fixtures"


def _build_graph(repo_root: Path, db_path: Path) -> nx.MultiDiGraph:
    store = SQLiteGraphStore(db_path)
    GraphBuilder(repo_root, store).build(incremental=False)
    g = to_digraph(store)
    store.close()
    classify_roles(g)
    return g


def test_detect_infrastructure_empty_graph_returns_zeroed_payload() -> None:
    g = nx.MultiDiGraph()
    payload = detect_infrastructure(g)
    assert payload["components"] == []
    assert payload["handlers"] == []
    assert payload["edges"] == []
    assert payload["metrics"]["components"] == 0


def test_detect_infrastructure_classifies_known_packages(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "app.py").write_text(
        "import redis\n"
        "import psycopg2\n"
        "from sqlalchemy import create_engine\n"
        "from celery import Celery\n"
        "import requests\n"
        "import boto3\n"
        "\n"
        "def use_redis():\n"
        "    return redis.Redis()\n",
        encoding="utf-8",
    )
    g = _build_graph(repo, tmp_path / "g.db")
    payload = detect_infrastructure(g)

    kinds = {c["kind"] for c in payload["components"]}
    labels = {c["label"] for c in payload["components"]}
    assert "CACHE" in kinds, "redis should be detected as CACHE"
    assert "DB" in kinds, "psycopg2 should be detected as DB"
    assert "ORM" in kinds, "sqlalchemy should be detected as ORM"
    assert "QUEUE" in kinds, "celery should be detected as QUEUE"
    assert "HTTP_CLIENT" in kinds, "requests should be detected as HTTP_CLIENT"
    assert "OBJECT_STORE" in kinds, "boto3 should be detected as OBJECT_STORE"
    assert "Redis" in labels


def test_detect_infrastructure_picks_up_commonjs_require(tmp_path: Path) -> None:
    """CommonJS Node projects use require(); detection should still work."""
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "server.js").write_text(
        'const express = require("express");\n'
        'const mongoose = require("mongoose");\n'
        'const Redis = require("ioredis");\n'
        'const { Queue } = require("bullmq");\n'
        '\n'
        'const app = express();\n'
        'mongoose.connect("mongodb://localhost/db");\n',
        encoding="utf-8",
    )
    g = _build_graph(repo, tmp_path / "g.db")
    payload = detect_infrastructure(g)
    kinds = {c["kind"] for c in payload["components"]}
    assert "WEB_SERVER" in kinds, "express via require() should be WEB_SERVER"
    assert "ORM" in kinds, "mongoose via require() should be ORM"
    assert "CACHE" in kinds, "ioredis via require() should be CACHE"
    assert "QUEUE" in kinds, "bullmq via require() should be QUEUE"


def test_detect_infrastructure_picks_up_typescript_imports(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "server.ts").write_text(
        "import express from 'express';\n"
        "import Redis from 'ioredis';\n"
        "import { Queue } from 'bullmq';\n"
        "import { Pool } from 'pg';\n"
        "\n"
        "const app = express();\n"
        "const cache = new Redis();\n"
        "const queue = new Queue('jobs');\n"
        "const pool = new Pool();\n",
        encoding="utf-8",
    )
    g = _build_graph(repo, tmp_path / "g.db")
    payload = detect_infrastructure(g)

    kinds = {c["kind"] for c in payload["components"]}
    assert "WEB_SERVER" in kinds, "express should be detected as WEB_SERVER"
    assert "CACHE" in kinds, "ioredis should be detected as CACHE"
    assert "QUEUE" in kinds, "bullmq should be detected as QUEUE"
    assert "DB" in kinds, "pg should be detected as DB"


def test_detect_infrastructure_lists_handlers_with_components(
    tmp_path: Path,
) -> None:
    """A FastAPI-style handler that imports redis should report it reachable."""
    import shutil
    repo = tmp_path / "repo"
    repo.mkdir()
    shutil.copytree(FIXTURES / "roles", repo / "pkg")
    # Inject a redis import into the fastapi_app fixture so the handler has
    # a reachable infra component.
    fastapi_path = repo / "pkg" / "fastapi_app.py"
    text = fastapi_path.read_text(encoding="utf-8")
    fastapi_path.write_text("import redis\n" + text, encoding="utf-8")

    g = _build_graph(repo, tmp_path / "g.db")
    payload = detect_infrastructure(g)

    # Should detect at least one HANDLER (the FastAPI fixture has 2).
    assert payload["metrics"]["handlers"] >= 2
    handler_paths = {h["path"] for h in payload["handlers"]}
    assert "/health" in handler_paths
    assert "/items" in handler_paths

    # The redis component should be detected and reachable from at least one
    # of the handlers (they live in the same file that now imports redis).
    redis_components = [
        c for c in payload["components"] if c["label"] == "Redis"
    ]
    assert redis_components, "redis component should appear"
    redis_id = redis_components[0]["id"]
    handler_with_redis = [
        h for h in payload["handlers"] if redis_id in h["components"]
    ]
    assert handler_with_redis, (
        "expected at least one handler to reach the redis component"
    )


def test_detect_infrastructure_payload_shape() -> None:
    """The payload must satisfy the contract the dashboard view depends on."""
    g = nx.MultiDiGraph()
    payload = detect_infrastructure(g)
    # Top-level keys.
    assert set(payload.keys()) == {"components", "handlers", "edges", "metrics"}
    # Metrics keys.
    assert set(payload["metrics"].keys()) == {
        "components", "handlers", "import_sites", "by_kind",
    }


def test_detect_infrastructure_ignores_unknown_packages(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "app.py").write_text(
        "import os\n"
        "import sys\n"
        "from pathlib import Path\n"
        "import some_random_internal_lib\n",
        encoding="utf-8",
    )
    g = _build_graph(repo, tmp_path / "g.db")
    payload = detect_infrastructure(g)
    assert payload["components"] == []


@pytest.mark.parametrize(
    "import_line,expected_kind,expected_label",
    [
        ("import redis", "CACHE", "Redis"),
        ("import psycopg2", "DB", "PostgreSQL"),
        ("from sqlalchemy import create_engine", "ORM", "SQLAlchemy"),
        ("from fastapi import FastAPI", "WEB_SERVER", "FastAPI"),
        ("from flask import Flask", "WEB_SERVER", "Flask"),
        ("import boto3", "OBJECT_STORE", "AWS (boto3)"),
        ("import requests", "HTTP_CLIENT", "requests"),
        ("from pymongo import MongoClient", "DB", "MongoDB"),
        ("import stripe", "EXTERNAL_API", "Stripe"),
    ],
)
def test_python_imports_classify_correctly(
    tmp_path: Path,
    import_line: str,
    expected_kind: str,
    expected_label: str,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "app.py").write_text(import_line + "\n", encoding="utf-8")
    g = _build_graph(repo, tmp_path / "g.db")
    payload = detect_infrastructure(g)
    kinds = {c["kind"] for c in payload["components"]}
    labels = {c["label"] for c in payload["components"]}
    assert expected_kind in kinds, (
        f"{import_line!r} should produce kind={expected_kind}; got {kinds}"
    )
    assert expected_label in labels, (
        f"{import_line!r} should produce label={expected_label}; got {labels}"
    )
