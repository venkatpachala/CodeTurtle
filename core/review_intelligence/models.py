from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Literal

from pydantic import BaseModel, Field
from core.models import FindingSeverity, SpecialistFinding, SpecialistReview
from core.investigation.models import InvestigationAsk


class ReviewerKind(str, Enum):
    CORRECTNESS = "correctness"
    CODE_QUALITY = "code_quality"
    SECURITY = "security"
    PERFORMANCE = "performance"
    CONCURRENCY = "concurrency"
    TESTING = "testing"
    API_COMPAT = "api_compat"
    DOCUMENTATION = "documentation"
    ARCHITECTURE = "architecture"


class RetrievalQuestion(BaseModel):
    question: str
    purpose: str = ""
    prefer_paths: List[str] = Field(default_factory=list)
    prefer_symbols: List[str] = Field(default_factory=list)


class ReviewPlan(BaseModel):
    intent_summary: str = ""
    risk_level: str = "medium"
    reviewers: List[ReviewerKind] = Field(default_factory=list)
    retrieval_questions: List[RetrievalQuestion] = Field(default_factory=list)
    investigate: List[InvestigationAsk] = Field(default_factory=list)
    focus_notes: List[str] = Field(default_factory=list)
    skip_reasons: Dict[str, str] = Field(default_factory=dict)


class GroundedFinding(BaseModel):
    title: str
    severity: str = "medium"
    confidence: float = 0.5
    evidence_refs: List[str] = Field(default_factory=list)
    reasoning: str = ""
    recommendation: str = ""
    reviewer: str = ""


class CritiqueResult(BaseModel):
    kept: List[GroundedFinding] = Field(default_factory=list)
    dropped: List[Dict[str, Any]] = Field(default_factory=list)
    notes: str = ""


class MergeDecision(BaseModel):
    recommendation: str
    confidence: float = 0.5
    summary: str = ""
    blocking_issues: List[str] = Field(default_factory=list)
    residual_risks: List[str] = Field(default_factory=list)
