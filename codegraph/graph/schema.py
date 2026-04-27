"""Graph schema: Node, Edge, and ID generation."""
from __future__ import annotations

import hashlib
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class NodeKind(str, Enum):
    FILE = "FILE"
    MODULE = "MODULE"
    CLASS = "CLASS"
    FUNCTION = "FUNCTION"
    METHOD = "METHOD"
    VARIABLE = "VARIABLE"
    PARAMETER = "PARAMETER"
    IMPORT = "IMPORT"
    TEST = "TEST"


class EdgeKind(str, Enum):
    DEFINED_IN = "DEFINED_IN"
    IMPORTS = "IMPORTS"
    CALLS = "CALLS"
    INHERITS = "INHERITS"
    IMPLEMENTS = "IMPLEMENTS"
    READS = "READS"
    WRITES = "WRITES"
    RETURNS = "RETURNS"
    PARAM_OF = "PARAM_OF"
    TESTED_BY = "TESTED_BY"
    # v0.2 cross-stack data-flow edges (populated by DF1 / DF2 extractors).
    # Reserved here so DF1/DF2 agents don't both edit this enum in parallel.
    ROUTE = "ROUTE"               # HANDLER → URL pattern (DF1, FastAPI/Flask)
    READS_FROM = "READS_FROM"     # function → SQLAlchemy model on read (DF1)
    WRITES_TO = "WRITES_TO"       # function → SQLAlchemy model on write (DF1)
    FETCH_CALL = "FETCH_CALL"     # frontend call site → URL string (DF2, fetch/axios)


class Node(BaseModel):
    id: str
    kind: NodeKind
    name: str
    qualname: str
    file: str
    line_start: int
    line_end: int
    signature: str | None = None
    docstring: str | None = None
    content_hash: str | None = None
    language: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class Edge(BaseModel):
    src: str
    dst: str
    kind: EdgeKind
    file: str | None = None
    line: int | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


def make_node_id(kind: NodeKind, qualname: str, file: str) -> str:
    """Stable BLAKE2b-128 hex hash of (kind, qualname, file)."""
    data = f"{kind.value}:{qualname}:{file}".encode()
    return hashlib.blake2b(data, digest_size=16).hexdigest()
