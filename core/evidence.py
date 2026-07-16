from pydantic import BaseModel, Field
from typing import List, Dict, Any
from langchain_core.documents import Document


class Evidence(BaseModel):
    """Rich evidence package for agents."""

    path: str
    retrieval_type: str  # "vector", "symbol", "metadata", "dependency"
    score: float
    document: Document
    symbols: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    reason: str = ""  # Why this evidence was retrieved


class EvidencePackage(BaseModel):
    """Structured context for the agent swarm."""

    query: str
    evidences: List[Evidence] = Field(default_factory=list)
    summary: str = ""
    affected_files: List[str] = Field(default_factory=list)
    related_symbols: List[str] = Field(default_factory=list)
    dependencies: List[str] = Field(default_factory=list)
    previous_reviews: List[dict] = Field(default_factory=list)