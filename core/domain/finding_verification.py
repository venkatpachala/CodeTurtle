"""Inspectable finding decisions; source grounding is distinct from semantic truth."""
from __future__ import annotations

from typing import Literal
import hashlib
import json

from pydantic import Field, model_validator

from core.domain.observations import SourceCitation, SourceObservation
from core.domain.review_contracts import ContentHash, DomainRecord, NonBlank, Refs

CLAIM_FIELDS = ("file", "symbol", "claim", "existing_code", "invariant", "violating_condition", "expected", "actual", "execution_path")


class FindingClaim(DomainRecord):
    file: NonBlank
    symbol: str
    claim: str
    existing_code: NonBlank
    invariant: NonBlank
    violating_condition: NonBlank
    expected: str
    actual: str
    execution_path: tuple[str, ...]

    @property
    def fingerprint(self) -> str:
        return hashlib.sha256(json.dumps(self.model_dump(mode="json"), sort_keys=True).encode()).hexdigest()


class FindingDecision(DomainRecord):
    verdict: Literal["supported", "refuted", "unresolved"]
    checked_trigger: NonBlank
    rationale: NonBlank
    path_analysis: NonBlank
    supporting_citations: tuple[SourceCitation, ...] = Field(max_length=8)
    counter_citations: tuple[SourceCitation, ...] = Field(max_length=8)
    missing_evidence: tuple[NonBlank, ...] = Field(max_length=12)
    refutation_basis: Literal["none", "head_guard", "unreachable_trigger", "equivalent_behavior", "preexisting_failure"] = "none"

    @model_validator(mode="after")
    def conclusive_requires_evidence(self) -> FindingDecision:
        if self.verdict != "unresolved" and self.missing_evidence:
            raise ValueError("missing evidence requires unresolved verdict")
        if self.verdict == "supported" and not self.supporting_citations:
            raise ValueError("support requires source citations")
        if self.verdict == "refuted" and (not self.counter_citations or self.refutation_basis == "none"):
            raise ValueError("refutation requires counterevidence and an explicit basis")
        return self


class VerificationAttempt(DomainRecord):
    prompt_sha256: ContentHash
    response: str = Field(max_length=16_000)
    attempt: int = Field(ge=1, le=2)


class FindingVerificationRecord(DomainRecord):
    id: NonBlank
    candidate_id: NonBlank
    candidate_fingerprint: ContentHash
    claim: FindingClaim
    snapshot_id: ContentHash | None = None
    verdict: Literal["supported", "refuted", "unresolved"] = "unresolved"
    status: Literal["completed", "invalid_response", "provider_error", "internal_error", "budget_exhausted", "context_unavailable"]
    reason: NonBlank
    observation_refs: Refs = ()
    decision: FindingDecision | None = None
    attempts: tuple[VerificationAttempt, ...] = ()
    hints: tuple[str, ...] = ()
    prompt_version: NonBlank

    @model_validator(mode="after")
    def validate_outcome(self) -> FindingVerificationRecord:
        if self.candidate_fingerprint != self.claim.fingerprint:
            raise ValueError("verification claim fingerprint mismatch")
        if self.decision and self.decision.checked_trigger != self.claim.violating_condition:
            raise ValueError("verification decision addresses another trigger")
        if self.decision and (self.status != "completed" or self.verdict != self.decision.verdict):
            raise ValueError("verification decision and recorded outcome disagree")
        if self.verdict != "unresolved" and (
            self.status != "completed" or self.decision is None or self.decision.verdict != self.verdict
            or self.snapshot_id is None or not self.observation_refs
        ):
            raise ValueError("conclusive finding verdict requires completed grounded decision")
        return self

    def validate_sources(self, observations: dict[str, SourceObservation]) -> None:
        for ref in self.observation_refs:
            if ref not in observations or observations[ref].snapshot_id != self.snapshot_id:
                raise ValueError("verification references missing or foreign snapshot observations")
        if self.decision is None:
            return
        permitted = {ref: observations[ref] for ref in self.observation_refs}
        support = [(citation, citation.validate_against(permitted)) for citation in self.decision.supporting_citations]
        counter = [(citation, citation.validate_against(permitted)) for citation in self.decision.counter_citations]
        if self.verdict == "supported" and not any(
            obs.path == self.claim.file and obs.revision_side == "head" and obs.status == "success"
            and " ".join(self.claim.existing_code.split()) in " ".join(citation.quote.split())
            for citation, obs in support
        ):
            raise ValueError("supported verification lacks candidate HEAD evidence")
        if self.verdict == "refuted" and not any(obs.revision_side == "head" and obs.status == "success" for _, obs in counter):
            raise ValueError("refuted verification lacks active HEAD counterevidence")
