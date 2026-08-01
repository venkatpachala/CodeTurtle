from __future__ import annotations
from typing import List, Optional, Literal
from pydantic import BaseModel, Field
from .node import NodeID


SymbolKind = Literal[
    "module",
    "class",
    "function",
    "method",
    "variable",
    "constant",
    "import",
    "unknown",
]


class SourceSpan(BaseModel):
    start_line: int
    end_line: int
    start_col: Optional[int] = None
    end_col: Optional[int] = None


class Symbol(BaseModel):
    node_id: NodeID
    name: str
    qualified_name: str
    kind: SymbolKind
    language: str = "python"
    file_path: str
    span: Optional[SourceSpan] = None
    visibility: Optional[str] = None          # public / private / protected
    docstring: Optional[str] = None
    decorators: List[str] = Field(default_factory=list)
    parent_qualified_name: Optional[str] = None  # for methods → class