"""Phase 3 investigation objects. A hypothesis is not a shipped finding."""

from __future__ import annotations

from typing import List, Literal, Optional

from pydantic import BaseModel, Field


class EvidenceItem(BaseModel):
    id: str
    source: Literal["graphify", "diff", "github"] = "graphify"
    kind: Literal["query", "node", "neighbors", "pr_impact", "hunk"] = "query"
    path: str = ""
    symbol: Optional[str] = None
    text: str = ""


HypothesisStatus = Literal["KEEP", "PLAUSIBLE", "REJECTED", "UNRESOLVED"]


class Hypothesis(BaseModel):
    id: str
    claim: str = ""
    file: str = ""
    file_hint: Optional[str] = None
    symbol: Optional[str] = None
    question: str = ""
    status: Literal["open", "confirmed", "rejected", "uncertain"] = "open"
    evidence_ids: List[str] = Field(default_factory=list)
    needs_investigation: bool = True
    finding_id: Optional[str] = None
    category: str = "review"
    title: str = ""
    hypothesis_kind: Optional[HypothesisStatus] = None


class InvestigationAsk(BaseModel):
    """Planner output: one Graphify follow-up about a changed file."""

    file: str
    symbol: Optional[str] = None
    ask: str = "neighbors"  # neighbors | node | callers | impact | query


class GraphifyCall(BaseModel):
    """Deterministic tool plan item. Maps 1:1 to existing Graphify MCP tools."""

    tool: Literal["get_node", "get_neighbors", "query", "get_pr_impact"]
    label: str = ""
    hypothesis_id: Optional[str] = None
    path: str = ""
    symbol: Optional[str] = None
    question: str = ""
    pr_number: Optional[int] = None
    repo: Optional[str] = None
