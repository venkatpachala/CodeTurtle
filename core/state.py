from typing import List, Annotated, TypedDict
from operator import add

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

    code_analysis: ReviewOutput
    critique: ReviewOutput
    final_comment: ReviewOutput

    model_used: str
    traces: Annotated[List[dict], add]
    recommendation: str