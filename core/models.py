from pydantic import BaseModel, Field
from typing import List, Literal, Optional, Dict, Any


class PRUnderstanding(BaseModel):
    """Structured understanding of a Pull Request."""

    summary: str = Field(..., description="One-paragraph summary of what this PR does")
    
    change_type: List[Literal[
        "feature", "bugfix", "refactor", "docs", "test", 
        "config", "dependency", "api", "ui", "performance", "security", "chore"
    ]] = Field(..., description="Primary categories of change")

    risk_level: Literal["low", "medium", "high", "critical"] = Field(
        ..., description="Overall risk of this change"
    )

    affected_areas: List[str] = Field(
        ..., description="High-level areas affected (e.g. 'authentication', 'memory system', 'API layer')"
    )

    files_summary: List[str] = Field(
        ..., description="Short description of key files changed"
    )

    focus_areas: List[str] = Field(
        ..., description="What the specialized reviewers should pay special attention to"
    )

    potential_risks: List[str] = Field(
        default_factory=list,
        description="Potential risks or things that could go wrong"
    )

    has_tests: bool = Field(..., description="Whether tests were added or modified")
    has_docs: bool = Field(..., description="Whether documentation was updated")


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


class ReviewOutput(BaseModel):
    """Structured output for review agents."""
    summary: str
    recommendation: Literal["MERGE", "REQUEST_CHANGES", "COMMENT"]
    confidence: float = 0.5


class Findings(BaseModel):
    """Wrapper for list of findings."""
    findings: List[Finding]