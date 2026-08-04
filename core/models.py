from __future__ import annotations

from enum import Enum
from typing import List, Literal, Dict, Any, Optional

from pydantic import BaseModel, Field

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
    changed_files: list[str] = Field(default_factory=list)
    added_functions: list[str] = Field(default_factory=list)
    modified_functions: list[str] = Field(default_factory=list)
    modified_classes: list[str] = Field(default_factory=list)
    removed_functions: list[str] = Field(default_factory=list)
    constants_added: list[str] = Field(default_factory=list)

    insertions: int = 0
    deletions: int = 0
    languages: list[str] = Field(default_factory=list)

    tests_added_or_modified: bool = False
    config_changed: bool = False
    documentation_changed: bool = False
    added_test_functions: list[str] = Field(default_factory=list)
    modified_test_functions: list[str] = Field(default_factory=list)

    high_risk_files: list[str] = Field(default_factory=list)
    high_risk_reasons: dict[str, str] = Field(default_factory=dict)

    logic_changes: list[str] = Field(default_factory=list)
    behavior_changes: list[str] = Field(default_factory=list)
    review_hotspots: list[str] = Field(default_factory=list)
    architectural_changes: list[str] = Field(default_factory=list)


class FindingSeverity(str, Enum):
    blocking = "blocking"
    concern = "concern"
    question = "question"
    suggestion = "suggestion"
    nit = "nit"
    verified = "verified"   # positive confirmation


class SpecialistFinding(BaseModel):
    severity: FindingSeverity = FindingSeverity.concern
    title: str
    detail: str
    evidence_paths: list[str] = Field(default_factory=list)  # optional anchors
    related_symbols: list[str] = Field(default_factory=list)
    confidence: float = 0.5  # 0-1


class SpecialistReview(BaseModel):
    """One specialist's full review — never 'empty means good' without verified items."""
    summary: str = ""  # 2-4 sentences: what was checked, what looks sound
    findings: list[SpecialistFinding] = Field(default_factory=list)
    assumptions_noted: list[str] = Field(default_factory=list)
    residual_risks: list[str] = Field(default_factory=list)
    no_blocking_issues: bool = True


class Finding(BaseModel):
    id: str = "finding-0"
    title: str
    description: str = ""
    severity: Literal["low", "medium", "high", "critical", "blocking", "concern", "question", "suggestion", "nit", "verified"] = "medium"
    confidence: float = 0.5
    evidence: List[str] = Field(default_factory=list)
    reasoning: str = ""
    recommendation: str = ""
    category: str = "review"


class ReviewOutput(BaseModel):
    summary: str
    recommendation: Literal["MERGE", "REQUEST_CHANGES", "COMMENT"]
    confidence: float = 0.5


class Findings(BaseModel):
    findings: List[Finding] = Field(default_factory=list)