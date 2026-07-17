from typing import List, Annotated, TypedDict
from operator import add
from pydantic import BaseModel, Field
from typing import List, Optional, Literal
from typing import List, Optional, Dict, Any
from core.models import PRAnalysis, Finding
from datetime import datetime
import operator

class ReviewOutput(TypedDict):
    summary: str
    recommendation: str
    confidence: float

class ReviewState(TypedDict):
    repo: str
    number: int
    title: str
    body: str
    author: str
    full_diff: str
    files_changed: List[str]

    context_from_kb: str
    summarized_context: str
    context_summary: str

    code_analysis: Dict
    critique: Dict
    final_comment: Dict

    model_used: str
    traces: List[dict]
    recommendation: str
    traces: Annotated[List[dict], operator.add]

    # Review Intelligence
    pr_understanding: Optional[dict] = None
    pr_analysis: Optional[PRAnalysis] = None
    evidence_package: Optional[Dict] = None
    correctness_findings: List[Finding] = Field(default_factory=list)
    quality_findings: List[Finding] = Field(default_factory=list)
    findings: List[Finding] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=datetime.now)

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

