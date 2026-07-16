from pydantic import BaseModel, Field
from typing import List, Optional

class CodeReviewFindings(BaseModel):
    bugs: List[str] = Field(default_factory=list)
    architecture_issues: List[str] = Field(default_factory=list)
    security_concerns: List[str] = Field(default_factory=list)
    testing_gaps: List[str] = Field(default_factory=list)
    positives: List[str] = Field(default_factory=list)
    suggestions: List[str] = Field(default_factory=list)

class ReviewOutput(BaseModel):
    summary: str
    findings: CodeReviewFindings
    recommendation: str = Field(..., description="MERGE, REQUEST_CHANGES, or COMMENT")
    confidence: float = Field(..., ge=0, le=1)