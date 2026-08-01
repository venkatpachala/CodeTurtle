from __future__ import annotations
from typing import List, Optional
from pydantic import BaseModel, Field
from .symbol import Symbol


class ParsedFile(BaseModel):
    path: str
    language: str
    content: str = ""
    symbols: List[Symbol] = Field(default_factory=list)
    imports: List[str] = Field(default_factory=list)
    line_count: int = 0
    size_bytes: int = 0