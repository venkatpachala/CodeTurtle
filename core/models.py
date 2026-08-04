from __future__ import annotations

from typing import List, Literal

from pydantic import BaseModel, Field


from pydantic import BaseModel, Field
from typing import List

class PRUnderstanding(BaseModel):
    summary: str
    change_type: List[str]
    risk_level: str  # low | medium | high | critical
    risk_rationale: str = ""

    # Causal / structural
    bug_mechanism: List[str] = Field(default_factory=list)
    affected_areas: List[str] = Field(default_factory=list)
    files_summary: List[str] = Field(default_factory=list)

    architectural_assumptions: List[str] = Field(default_factory=list)
    design_tradeoffs: List[str] = Field(default_factory=list)
    out_of_scope_noted: List[str] = Field(default_factory=list)

    focus_areas: List[str] = Field(default_factory=list)
    verification_targets: List[str] = Field(default_factory=list)
    potential_risks: List[str] = Field(default_factory=list)

    has_tests: bool = False
    has_docs: bool = False

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