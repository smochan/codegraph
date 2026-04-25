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
