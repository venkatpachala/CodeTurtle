"""Versioned product contract and deterministic release policy.

These records describe observed work, not model confidence. They contain no
credentials, network operations, or repository execution.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ReviewTarget(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    repo: str = ""
    number: int = Field(default=0, ge=0)
    base_sha: str = ""
    head_sha: str = ""
    diff_sha256: str = ""


class StageOutcome(BaseModel):
    stage: str
    status: Literal["succeeded", "degraded", "failed", "skipped", "timed_out"]
    code: str = ""
    detail: str = ""
    retryable: bool = False


class UnitAssessment(BaseModel):
    unit_id: str
    path: str
    status: Literal["inspected", "omitted", "unknown"] = "unknown"
    behavioral_delta: str = ""
    hypothesis_outcome: str = ""
    evidence_refs: list[str] = Field(default_factory=list)
    reason: str = ""

    @model_validator(mode="after")
    def inspection_requires_evidence(self) -> "UnitAssessment":
        if self.status == "inspected" and not (
            self.behavioral_delta.strip() and self.hypothesis_outcome.strip() and self.evidence_refs
        ):
            raise ValueError("inspection requires delta, hypothesis outcome, and evidence references")
        return self


class ReviewHealth(BaseModel):
    status: Literal["completed", "partial", "failed", "skipped"] = "partial"
    stages: list[StageOutcome] = Field(default_factory=list)


class ReviewCoverage(BaseModel):
    eligible: int = Field(default=0, ge=0)
    packed: int = Field(default=0, ge=0)
    inspected: int = Field(default=0, ge=0)
    assessments: list[UnitAssessment] = Field(default_factory=list)

    @model_validator(mode="after")
    def valid_counts(self) -> "ReviewCoverage":
        if not 0 <= self.inspected <= self.packed <= self.eligible:
            raise ValueError("coverage must satisfy inspected <= packed <= eligible")
        if len({a.unit_id for a in self.assessments}) != len(self.assessments):
            raise ValueError("duplicate unit assessment")
        return self

    @property
    def inspection_ratio(self) -> float | None:
        return self.inspected / self.eligible if self.eligible else None


class PolicyOutcome(BaseModel):
    decision: Literal["MERGE", "COMMENT", "REQUEST_CHANGES"] | None
    reasons: list[str]
    approval_eligible: bool = False


def evaluate_policy(*, health: ReviewHealth, coverage: ReviewCoverage,
                    findings: list, unresolved: list[dict], execution: dict,
                    classification: str = "") -> PolicyOutcome:
    """Single v4 verdict function. A failed analysis has no code verdict."""
    reasons: list[str] = []
    if health.status == "failed":
        return PolicyOutcome(decision=None, reasons=["analysis_failed"])
    if health.status == "skipped":
        return PolicyOutcome(decision=None, reasons=["analysis_skipped"])
    verified = [f for f in findings if f.verification_status == "verified" and f.kind == "defect"]
    blockers = [f for f in verified if f.blocking]
    if blockers:
        reasons.append("verified_blocker")
    if health.status != "completed":
        reasons.append("partial_analysis")
    if classification == "lockfile-only":
        reasons.append("lockfile_only")
    if coverage.eligible == 0:
        reasons.append("no_eligible_units")
    elif coverage.inspected != coverage.eligible:
        reasons.append("insufficient_inspection")
    if unresolved or any(f.verification_status in {"candidate", "uncertain"} for f in findings):
        reasons.append("unresolved_hypotheses")
    slices = [execution, *[x for x in (execution.get("python"), execution.get("js")) if isinstance(x, dict)]]
    failed_execution = any((x.get("failed") or 0) > 0 or
                           (not x.get("skipped", True) and x.get("exit_code") not in (None, 0)) for x in slices)
    inconclusive_execution = any(x.get("skip_reason") not in (None, "", "flag_off", "lockfile-only", "no_test_targets")
                                 for x in slices)
    if failed_execution or inconclusive_execution:
        reasons.append("execution_unattributed" if failed_execution else "execution_inconclusive")
    if blockers:
        return PolicyOutcome(decision="REQUEST_CHANGES", reasons=reasons)
    if reasons:
        return PolicyOutcome(decision="COMMENT", reasons=reasons)
    if verified:
        return PolicyOutcome(decision="COMMENT", reasons=["verified_nonblocking"])
    return PolicyOutcome(decision="MERGE", reasons=["complete_no_findings"], approval_eligible=True)
