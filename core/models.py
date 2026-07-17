from pydantic import BaseModel, Field
from typing import List, Literal, Optional, Dict, Any


class PRAnalysis(BaseModel):
    """Deterministic facts about the PR (no LLM needed)."""

    changed_files: List[str]
    modified_functions: List[str] = Field(default_factory=list)
    modified_classes: List[str] = Field(default_factory=list)
    tests_added_or_modified: bool = False
    config_changed: bool = False
    documentation_changed: bool = False
    insertions: int = 0
    deletions: int = 0
    languages: List[str] = Field(default_factory=list)
    high_risk_files: List[str] = Field(default_factory=list)


class Finding(BaseModel):
    """Canonical output of every reviewer."""

    id: str
    title: str
    description: str
    severity: Literal["low", "medium", "high", "critical"]
    confidence: float
    evidence: List[str]
    reasoning: str
    recommendation: str
    category: str