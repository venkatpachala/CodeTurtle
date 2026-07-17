from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional


class Evidence(BaseModel):
    path: str
    chunk_type: str = "module"
    start_line: Optional[int] = None
    end_line: Optional[int] = None
    symbols: List[str] = Field(default_factory=list)
    retrieval_type: str = "vector"
    content: str
    score: float = 0.0
    reason: str = ""


class EvidencePackage(BaseModel):
    query: str
    pr_understanding: Dict[str, Any] = Field(default_factory=dict)
    evidences: List[Evidence] = Field(default_factory=list)
    affected_files: List[str] = Field(default_factory=list)
    related_symbols: List[str] = Field(default_factory=list)
    summary: str = ""