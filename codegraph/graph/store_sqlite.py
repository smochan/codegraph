"""SQLite-backed graph store."""
from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import Any

from codegraph.graph.schema import Edge, EdgeKind, Node, NodeKind


class SQLiteGraphStore:
    def __init__(self, path: Path) -> None:
        self._path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        self._con = sqlite3.connect(str(path), check_same_thread=False)
        self._con.execute("PRAGMA foreign_keys = ON")
        self._con.execute("PRAGMA journal_mode = WAL")
        self._init_schema()

    def _init_schema(self) -> None:
        self._con.executescript(
            """
            CREATE TABLE IF NOT EXISTS nodes (
                id TEXT PRIMARY KEY,
                kind TEXT NOT NULL,
                name TEXT NOT NULL,
                qualname TEXT NOT NULL,
                file TEXT NOT NULL,
                line_start INTEGER NOT NULL,
                line_end INTEGER NOT NULL,
                signature TEXT,
                docstring TEXT,
                content_hash TEXT,
                language TEXT NOT NULL,
                metadata TEXT NOT NULL DEFAULT '{}'
            );
            CREATE INDEX IF NOT EXISTS idx_nodes_kind ON nodes(kind);
            CREATE INDEX IF NOT EXISTS idx_nodes_file ON nodes(file);
            CREATE TABLE IF NOT EXISTS edges (
                src TEXT NOT NULL,
                dst TEXT NOT NULL,
                kind TEXT NOT NULL,
                file TEXT,
                line INTEGER,
                metadata TEXT NOT NULL DEFAULT '{}',
                PRIMARY KEY (src, dst, kind)
            );
            CREATE INDEX IF NOT EXISTS idx_edges_src ON edges(src);
            CREATE INDEX IF NOT EXISTS idx_edges_dst ON edges(dst);
            CREATE INDEX IF NOT EXISTS idx_edges_kind ON edges(kind);
            CREATE TABLE IF NOT EXISTS meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            """
        )
        self._con.commit()

    def upsert_node(self, node: Node) -> None:
        self._con.execute(
            """INSERT OR REPLACE INTO nodes
               (id, kind, name, qualname, file, line_start, line_end,
                signature, docstring, content_hash, language, metadata)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                node.id, node.kind.value, node.name, node.qualname, node.file,
                node.line_start, node.line_end, node.signature, node.docstring,
                node.content_hash, node.language, json.dumps(node.metadata),
            ),
        )
        self._con.commit()

    def upsert_nodes(self, nodes: Iterable[Node]) -> None:
        rows = [
            (
                n.id, n.kind.value, n.name, n.qualname, n.file,
                n.line_start, n.line_end, n.signature, n.docstring,
                n.content_hash, n.language, json.dumps(n.metadata),
            )
            for n in nodes
        ]
        with self._con:
            self._con.executemany(
                """INSERT OR REPLACE INTO nodes
                   (id, kind, name, qualname, file, line_start, line_end,
                    signature, docstring, content_hash, language, metadata)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                rows,
            )

    def upsert_edge(self, edge: Edge) -> None:
        self._con.execute(
            """INSERT OR REPLACE INTO edges (src, dst, kind, file, line, metadata)
               VALUES (?,?,?,?,?,?)""",
            (
                edge.src, edge.dst, edge.kind.value, edge.file, edge.line,
                json.dumps(edge.metadata),
            ),
        )
        self._con.commit()

    def upsert_edges(self, edges: Iterable[Edge]) -> None:
        rows = [
            (e.src, e.dst, e.kind.value, e.file, e.line, json.dumps(e.metadata))
            for e in edges
        ]
        with self._con:
            self._con.executemany(
                """INSERT OR REPLACE INTO edges (src, dst, kind, file, line, metadata)
                   VALUES (?,?,?,?,?,?)""",
                rows,
            )

    def get_node(self, node_id: str) -> Node | None:
        cur = self._con.execute(
            "SELECT id, kind, name, qualname, file, line_start, line_end, "
            "signature, docstring, content_hash, language, metadata "
            "FROM nodes WHERE id=?",
            (node_id,),
        )
        row = cur.fetchone()
        if row is None:
            return None
        return self._row_to_node(row)

    def iter_nodes(
        self, kind: NodeKind | None = None, file: str | None = None
    ) -> Iterator[Node]:
        where: list[str] = []
        params: list[Any] = []
        if kind is not None:
            where.append("kind=?")
            params.append(kind.value)
        if file is not None:
            where.append("file=?")
            params.append(file)
        q = (
            "SELECT id, kind, name, qualname, file, line_start, line_end, "
            "signature, docstring, content_hash, language, metadata FROM nodes"
        )
        if where:
            q += " WHERE " + " AND ".join(where)
        cur = self._con.execute(q, params)
        for row in cur:
            yield self._row_to_node(row)

    def iter_edges(
        self,
        src: str | None = None,
        dst: str | None = None,
        kind: EdgeKind | None = None,
    ) -> Iterator[Edge]:
        where: list[str] = []
        params: list[Any] = []
        if src is not None:
            where.append("src=?")
            params.append(src)
        if dst is not None:
            where.append("dst=?")
            params.append(dst)
        if kind is not None:
            where.append("kind=?")
            params.append(kind.value)
        q = "SELECT src, dst, kind, file, line, metadata FROM edges"
        if where:
            q += " WHERE " + " AND ".join(where)
        cur = self._con.execute(q, params)
        for row in cur:
            yield Edge(
                src=row[0],
                dst=row[1],
                kind=EdgeKind(row[2]),
                file=row[3],
                line=row[4],
                metadata=json.loads(row[5]),
            )

    def delete_edge(self, src: str, dst: str, kind: EdgeKind) -> None:
        with self._con:
            self._con.execute(
                "DELETE FROM edges WHERE src=? AND dst=? AND kind=?",
                (src, dst, kind.value),
            )

    def count_unresolved_edges(self) -> int:
        row = self._con.execute(
            "SELECT COUNT(*) FROM edges WHERE dst LIKE 'unresolved::%'"
        ).fetchone()
        return int(row[0])

    def delete_file(self, path: str) -> None:
        cur = self._con.execute("SELECT id FROM nodes WHERE file=?", (path,))
        node_ids = [r[0] for r in cur.fetchall()]
        with self._con:
            for nid in node_ids:
                self._con.execute(
                    "DELETE FROM edges WHERE src=? OR dst=?", (nid, nid)
                )
            self._con.execute("DELETE FROM nodes WHERE file=?", (path,))
        with self._con:
            self._con.execute("DELETE FROM edges WHERE file=?", (path,))

    def count_nodes(self) -> int:
        row = self._con.execute("SELECT COUNT(*) FROM nodes").fetchone()
        return int(row[0])

    def count_edges(self) -> int:
        row = self._con.execute("SELECT COUNT(*) FROM edges").fetchone()
        return int(row[0])

    def set_meta(self, key: str, value: str) -> None:
        with self._con:
            self._con.execute(
                "INSERT OR REPLACE INTO meta (key, value) VALUES (?,?)",
                (key, value),
            )

    def get_meta(self, key: str) -> str | None:
        row = self._con.execute(
            "SELECT value FROM meta WHERE key=?", (key,)
        ).fetchone()
        return str(row[0]) if row else None

    def vacuum(self) -> None:
        self._con.execute("VACUUM")

    def close(self) -> None:
        self._con.close()

    @staticmethod
    def _row_to_node(row: tuple[Any, ...]) -> Node:
        return Node(
            id=row[0],
            kind=NodeKind(row[1]),
            name=row[2],
            qualname=row[3],
            file=row[4],
            line_start=row[5],
            line_end=row[6],
            signature=row[7],
            docstring=row[8],
            content_hash=row[9],
            language=row[10],
            metadata=json.loads(row[11]),
        )
