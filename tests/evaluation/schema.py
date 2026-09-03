"""Phase 5.1 — golden labels and review snapshots. Gates only, not comment quality."""

from __future__ import annotations

from typing import List, Literal, Optional

from pydantic import BaseModel, Field

from core.evaluation.snapshot import ReviewSnapshot

Classification = Literal["lockfile-only", "source", "mixed", "other"]
InvestigateExpect = Literal["run", "skip"]
ExecuteExpect = Literal["skip_disabled", "skip_lockfile-only", "any"]
Decision = Literal["MERGE", "COMMENT", "REQUEST_CHANGES"]

__all__ = [
    "CheckResult",
    "Classification",
    "GoldenCase",
    "ReviewSnapshot",
    "Scorecard",
]


class GoldenCase(BaseModel):
    id: str
    repo: str
    number: int
    classification: Classification
    must_include_files: List[str] = Field(default_factory=list)
    lockfile_only: bool = False
    investigate: InvestigateExpect = "run"
    skip_reason_contains: Optional[str] = None
    max_investigate_calls: int = 6
    keep_files_allowed: Optional[List[str]] = None
    trivia_keep_forbidden: bool = True
    qdrant: bool = False
    execute_default: ExecuteExpect = "skip_disabled"
    execute_even_with_flags: Optional[ExecuteExpect] = None
    tests_touched_max: Optional[int] = None
    final_allowed: List[str]
    forbid_request_changes_unless_supported_medium: bool = True
    notes: str = ""


class CheckResult(BaseModel):
    name: str
    passed: bool
    detail: str = ""


class Scorecard(BaseModel):
    case_id: str
    checks: List[CheckResult] = Field(default_factory=list)

    @property
    def ok(self) -> bool:
        return all(c.passed for c in self.checks)

    @property
    def passed_names(self) -> List[str]:
        return [c.name for c in self.checks if c.passed]

    @property
    def failed(self) -> List[CheckResult]:
        return [c for c in self.checks if not c.passed]
