from typing import List, Optional, Dict, Any, Annotated
import operator
from datetime import datetime
from typing_extensions import TypedDict
from pydantic import BaseModel, Field
from typing import List, Literal, Optional, Dict, Any
from core.models import PRAnalysis, Finding


class ReviewOutput(BaseModel):
    """Structured output for review agents."""
    summary: str
    recommendation: Literal["MERGE", "REQUEST_CHANGES", "COMMENT"]
    confidence: float = 0.5


class ReviewState(TypedDict):
    """Main state for the review graph."""

    # Basic PR Info
    repo: str
    number: int
    title: str
    body: str
    author: str
    full_diff: str
    files_changed: List[str]

    # Context & Retrieval
    context_from_kb: str
    summarized_context: str
    context_summary: str

    # Review Intelligence
    pr_understanding: Optional[dict] = None
    pr_analysis: Optional[PRAnalysis] = None
    evidence_package: Optional[Dict] = None

    # Specialized Findings
    correctness_findings: List[Finding]
    quality_findings: List[Finding]

    # Aggregated Findings
    findings: List[Finding]

    # Agent Outputs
    code_analysis: Dict
    critique: Dict
    final_comment: Dict

    # Metadata
    model_used: str
    traces: Annotated[List[dict], operator.add]   # Fixed: reducer for parallel agents
    recommendation: str

    # Timestamps
    created_at: datetime = datetime.now()