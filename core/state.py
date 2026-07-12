from pydantic import BaseModel, Field
from typing import List, Dict, Any
from datetime import datetime

class ReviewState(BaseModel):
    # Input
    repo: str
    number: int
    event_type: str = "pr"
    title: str = ""
    body: str = ""
    author: str = ""
    diff: str | None = None
    files_changed: List[str] = Field(default_factory=list)

    # Knowledge Base Context
    context_from_kb: str = ""
    summarized_context: str = ""          # ← New field

    # Memory Context
    previous_reviews: list = Field(default_factory=list)

    # Agent Outputs
    context_summary: str = ""
    code_analysis: str = ""
    critique: str = ""
    recommendation: str = ""
    final_comment: str = ""

    # Metadata
    traces: List[Dict[str, Any]] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=datetime.now)
    model_used: str = ""

    class Config:
        arbitrary_types_allowed = True