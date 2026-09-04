from typing import List, NotRequired, Optional, Dict, Any, Annotated
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
    change_units: NotRequired[list]
    review_diff: NotRequired[str]
    review_coverage: NotRequired[dict]
    coverage_ratio: NotRequired[float]
    coverage_low: NotRequired[bool]
    policy_reason: NotRequired[str]
    coverage_merge_min: NotRequired[float]
    pr_facts: NotRequired[dict]
    validated_findings: NotRequired[list]
    classified_findings: NotRequired[list]
    hypothesis_pool: NotRequired[list]
    hypothesis_report: NotRequired[dict]
    validation_report: NotRequired[dict]
    hypotheses: NotRequired[list]
    investigation_evidence: NotRequired[list]
    investigation_report: NotRequired[dict]
    verification_report: NotRequired[dict]
    execution_report: NotRequired[dict]
    execute_tests: NotRequired[bool]
    execute_install: NotRequired[bool]
    pr_head_sha: NotRequired[str]
    execute_timeout_s: NotRequired[int]
    execute_max_files: NotRequired[int]
    execute_install_timeout_s: NotRequired[int]
    execute_allow_npm: NotRequired[bool]
    execute_allow_npm_scripts: NotRequired[bool]

    # Context & Retrieval
    context_from_kb: str
    summarized_context: str
    context_summary: str

    # Review Intelligence
    pr_understanding: Optional[dict] = None
    pr_analysis: Optional[PRAnalysis] = None
    evidence_package: Optional[Dict] = None
    review_plan: NotRequired[dict]  # or Optional[dict] = None

    # Specialized Findings
    correctness_findings: List[Finding]
    quality_findings: List[Finding]
    testing_findings: List[Finding]
    critique: dict
    merge_decision: dict
    review_plan: dict

    # Aggregated Findings
    findings: List[Finding]

    correctness_meta: dict
    testing_meta: dict
    quality_meta: dict

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