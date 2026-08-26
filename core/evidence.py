from pydantic import BaseModel
from typing import List, Optional


class Evidence(BaseModel):
    path: str
    content: str
    score: float = 0.0
    symbols: List[str] = []
    retrieval_type: str = "vector"

    # Chunk metadata (required by ContextBuilder)
    chunk_type: Optional[str] = "module"
    start_line: Optional[int] = None
    end_line: Optional[int] = None

    # Provenance (for debugging and ranking)
    source_query: Optional[str] = None
    query_category: Optional[str] = None
    query_weight: Optional[float] = None
    metadata: Optional[dict] = None

    @property
    def page_content(self) -> str:
        return self.content


class EvidencePackage(BaseModel):
    evidences: List[Evidence]
    query: str
    pr_understanding: dict = {}
    summary: str = ""
    affected_files: List[str] = []
    related_symbols: List[str] = []