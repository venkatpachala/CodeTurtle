"""Typed, revision-bound records for requirement verification."""

from __future__ import annotations

from typing import Annotated, Literal, Self

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, StringConstraints, computed_field, model_validator

NonBlank = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
ContentHash = Annotated[str, StringConstraints(pattern=r"^[0-9a-fA-F]{64}$")]
RevisionSHA = Annotated[str, StringConstraints(pattern=r"^(?:[0-9a-fA-F]{40}|[0-9a-fA-F]{64})$")]
Count = Annotated[int, Field(ge=0, strict=True)]
RequirementStatus = Literal["not_assessed", "unverified", "verified", "violated"]
InvestigationStatus = Literal[
    "planned", "gathering_evidence", "evaluating", "confirmed", "disproved", "unresolved", "error", "cancelled",
]
EvidenceKind = Literal["source", "requirement", "contract", "historical", "execution", "static_proof", "model_inference"]

_CODE_EVIDENCE = {"source", "historical", "execution", "static_proof"}
_BEHAVIOR_EVIDENCE = {"source", "contract", "execution", "static_proof"}


class _ContractRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class IntentSource(_ContractRecord):
    """Immutable identity of a captured statement of intent."""

    id: NonBlank
    source_type: Literal["issue", "specification", "task", "pr", "policy", "code"]
    source_ref: NonBlank
    content_hash: ContentHash
    revision: NonBlank | None = None
    captured_at: AwareDatetime | None = None
    authority_level: Literal["authoritative", "contextual", "untrusted"] = "untrusted"
    trusted_for: tuple[NonBlank, ...] = ()

    @model_validator(mode="after")
    def require_capture_identity(self) -> Self:
        if self.revision is None and self.captured_at is None:
            raise ValueError("intent source requires a revision or captured_at")
        return self


class Requirement(_ContractRecord):
    """An independently checkable acceptance criterion grounded in intent."""

    id: NonBlank
    description: NonBlank
    acceptance_criterion: NonBlank
    source_refs: tuple[NonBlank, ...] = Field(min_length=1)
    kind: Literal["functional", "non_functional", "constraint"] = "functional"
    inferred: bool = False


class RequirementAssessment(_ContractRecord):
    """The observed verification outcome for one requirement in a review."""

    requirement_id: NonBlank
    status: RequirementStatus = "not_assessed"
    evidence_ids: tuple[NonBlank, ...] = ()
    reason: str = ""

    @model_validator(mode="after")
    def validate_outcome(self) -> Self:
        if self.status in {"verified", "violated"} and not self.evidence_ids:
            raise ValueError(f"{self.status} assessment requires evidence")
        if self.status == "not_assessed" and self.evidence_ids:
            raise ValueError("not_assessed cannot cite verification evidence")
        return self


class InvestigationRecord(_ContractRecord):
    """A hypothesis and the claims and evidence examined during investigation."""

    id: NonBlank
    hypothesis: NonBlank
    status: InvestigationStatus = "planned"
    claim_ids: tuple[NonBlank, ...] = ()
    evidence_ids: tuple[NonBlank, ...] = ()
    reason: str = ""

    @model_validator(mode="after")
    def require_evidence_for_resolution(self) -> Self:
        if self.status in {"confirmed", "disproved"} and not self.evidence_ids:
            raise ValueError(f"{self.status} investigation requires evidence")
        return self


class EvidenceRecord(_ContractRecord):
    """A content-addressed observation and its explicit claim relationships."""

    id: NonBlank
    kind: EvidenceKind
    source_ref: NonBlank
    content_hash: ContentHash
    revision_sha: RevisionSHA | None = None
    revision_side: Literal["base", "head"] | None = None
    supports_claim_ids: tuple[NonBlank, ...] = ()
    contradicts_claim_ids: tuple[NonBlank, ...] = ()
    limitations: tuple[NonBlank, ...] = ()

    @model_validator(mode="after")
    def validate_provenance(self) -> Self:
        has_revision = self.revision_sha is not None
        has_side = self.revision_side is not None
        if has_revision != has_side or (self.kind in _CODE_EVIDENCE and not has_revision):
            raise ValueError("evidence requires both a revision SHA and revision side")
        if set(self.supports_claim_ids).intersection(self.contradicts_claim_ids):
            raise ValueError("evidence cannot both support and contradict the same claim")
        return self

    @property
    def can_establish_head_behavior(self) -> bool:
        return self.revision_side == "head" and self.kind in _BEHAVIOR_EVIDENCE


class RequirementCoverage(_ContractRecord):
    """Counts verification outcomes independently of source-unit inspection."""

    total: Count = 0
    verified: Count = 0
    violated: Count = 0
    unverified: Count = 0
    not_assessed: Count = 0

    @model_validator(mode="after")
    def validate_counts(self) -> Self:
        if self.assessed + self.not_assessed != self.total:
            raise ValueError("requirement coverage outcomes must add up to total")
        return self

    @computed_field
    @property
    def assessed(self) -> int:
        return self.verified + self.violated + self.unverified

    @computed_field
    @property
    def ratio(self) -> float | None:
        return self.assessed / self.total if self.total else None
