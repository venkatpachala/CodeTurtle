from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class RelationKind(str, Enum):
    CALLS = "call"
    IMPORTS = "import"
    DEFINES = "defines"
    USES = "uses"
    FIELD = "field"
    TEST = "test"
    UNKNOWN = "unknown"


class ConfidenceTag(str, Enum):
    EXTRACTED = "EXTRACTED"
    INFERRED = "INFERRED"
    AMBIGUOUS = "AMBIGUOUS"
    UNKNOWN = "UNKNOWN"


class GraphNode(BaseModel):
    id: str
    label: str
    kind: str = "unknown"
    path: Optional[str] = None
    start_line: Optional[int] = None
    end_line: Optional[int] = None
    community: Optional[str] = None
    raw: Dict[str, Any] = Field(default_factory=dict)


class GraphEdge(BaseModel):
    source: str
    target: str
    relation: str = RelationKind.UNKNOWN.value
    confidence: ConfidenceTag = ConfidenceTag.UNKNOWN
    raw: Dict[str, Any] = Field(default_factory=dict)


class NeighborResult(BaseModel):
    node: GraphNode
    neighbors: List[GraphNode] = Field(default_factory=list)
    edges: List[GraphEdge] = Field(default_factory=list)
    raw_text: str = ""


class PathResult(BaseModel):
    source: str
    target: str
    hops: List[str] = Field(default_factory=list)
    raw_text: str = ""
    found: bool = False


class PRImpact(BaseModel):
    pr_number: int
    repo: Optional[str] = None
    files_changed: List[str] = Field(default_factory=list)
    communities_affected: List[str] = Field(default_factory=list)
    nodes_touched: List[str] = Field(default_factory=list)
    raw_text: str = ""


class GraphStats(BaseModel):
    raw_text: str = ""
    extra: Dict[str, Any] = Field(default_factory=dict)


class KnowledgeQueryResult(BaseModel):
    question: str
    raw_text: str
    nodes: List[GraphNode] = Field(default_factory=list)
    edges: List[GraphEdge] = Field(default_factory=list)
    source: str = "graphify"