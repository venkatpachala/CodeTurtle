from __future__ import annotations

from typing import List, Literal

from pydantic import BaseModel, Field


class PRUnderstanding(BaseModel):
    summary: str = Field(..., description="One-paragraph summary of what this PR does")
    change_type: List[
        Literal[
            "feature", "bugfix", "refactor", "docs", "test",
            "config", "dependency", "api", "ui", "performance", "security", "chore",
        ]
    ] = Field(..., description="Primary categories of change")
    risk_level: Literal["low", "medium", "high", "critical"] = Field(
        ..., description="Overall risk of this change"
    )
    affected_areas: List[str] = Field(
        ..., description="High-level areas affected"
    )
    files_summary: List[str] = Field(
        ..., description="Short description of key files changed"
    )
    focus_areas: List[str] = Field(
        ..., description="What specialized reviewers should focus on"
    )
    potential_risks: List[str] = Field(default_factory=list)
    has_tests: bool = Field(..., description="Whether tests were added or modified")
    has_docs: bool = Field(..., description="Whether documentation was updated")


class PRAnalysis(BaseModel):
    changed_files: List[str]
    modified_functions: List[str] = Field(default_factory=list)
    modified_classes: List[str] = Field(default_factory=list)
    added_functions: List[str] = Field(default_factory=list)
    tests_added_or_modified: bool = False
    config_changed: bool = False
    documentation_changed: bool = False
    insertions: int = 0
    deletions: int = 0
    languages: List[str] = Field(default_factory=list)
    high_risk_files: List[str] = Field(default_factory=list)


class Finding(BaseModel):
    id: str
    title: str
    description: str
    severity: Literal["low", "medium", "high", "critical"]
    confidence: float
    evidence: List[str] = Field(default_factory=list)
    reasoning: str
    recommendation: str
    category: str


class ReviewOutput(BaseModel):
    summary: str
    recommendation: Literal["MERGE", "REQUEST_CHANGES", "COMMENT"]
    confidence: float = 0.5


class Findings(BaseModel):
    findings: List[Finding] = Field(default_factory=list)