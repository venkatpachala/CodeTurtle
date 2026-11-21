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
    verification_method: Literal["model", "source_rule"] = "model"
    source_rule_id: str = ""

    @model_validator(mode="after")
    def validate_outcome(self) -> FindingVerificationRecord:
        if self.verification_method == "source_rule":
            if not self.source_rule_id or self.attempts or self.status != "completed" or self.verdict == "unresolved":
                raise ValueError("source-rule verification requires a conclusive completed result without model attempts")
        elif self.source_rule_id:
            raise ValueError("model verification cannot claim a source rule")
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
        if self.verification_method == "source_rule":
            from core.verification.none_len_contract import RULE_ID, verify_none_len
            from core.runtime.models import Candidate
            checked = verify_none_len(Candidate(bundle_id="source-recheck", **self.claim.model_dump(mode="json")), tuple(permitted.values()))
            if self.source_rule_id != RULE_ID or checked is None or checked != self.decision:
                raise ValueError("source-rule verdict cannot be reproduced from its recorded observations")
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
