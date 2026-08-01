from __future__ import annotations
from typing import Literal, Optional, Dict, Any
from pydantic import BaseModel, Field
from .node import NodeID


RelationType = Literal[
    "CONTAINS",
    "IMPORTS",
    "CALLS",
    "INHERITS",
    "IMPLEMENTS",
    "USES",
    "RETURNS",
    "RAISES",
    "TESTS",
    "DOCUMENTED_BY",
    "REFERENCES",
    "CHANGED_IN",
]


class Relationship(BaseModel):
    source_id: NodeID
    target_id: NodeID
    type: RelationType
    properties: Dict[str, Any] = Field(default_factory=dict)