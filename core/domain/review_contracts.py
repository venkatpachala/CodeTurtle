"""Immutable records and structural validation for intent-aware reviews.

ReviewKnowledge validates the relationships between records in one review.
A later adjudicator is responsible for evaluating what the evidence proves.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping
from enum import StrEnum
from typing import Annotated, Literal, Self

from pydantic import (
    AfterValidator,
    AliasChoices,
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    computed_field,
    model_validator,
)


class DomainRecord(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", revalidate_instances="always")


class SourceKind(StrEnum):
    TASK = "task"
    ISSUE = "issue"
    SPECIFICATION = "specification"
    REPOSITORY_POLICY = "repository_policy"
    PR_DESCRIPTION = "pr_description"
    CODE = "code"


class RequirementKind(StrEnum):
    FUNCTIONAL = "functional"
    NON_FUNCTIONAL = "non_functional"
    CONSTRAINT = "constraint"


class RequirementStatus(StrEnum):
    VERIFIED = "verified"
    VIOLATED = "violated"
    UNVERIFIED = "unverified"
    NOT_ASSESSED = "not_assessed"
    NOT_APPLICABLE = "not_applicable"


class InvestigationStatus(StrEnum):
    PLANNED = "planned"
    GATHERING_EVIDENCE = "gathering_evidence"
    EVALUATING = "evaluating"
    CONFIRMED = "confirmed"
    DISPROVED = "disproved"
    UNRESOLVED = "unresolved"
    ERROR = "error"
    CANCELLED = "cancelled"


class EvidenceKind(StrEnum):
    SOURCE = "source"
    REQUIREMENT = "requirement"
    CONTRACT = "contract"
    HISTORICAL = "historical"
    EXECUTION = "execution"
    STATIC_PROOF = "static_proof"
    MODEL_INFERENCE = "model_inference"


class RevisionSide(StrEnum):
    BASE = "base"
    HEAD = "head"


NonBlank = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
ContentHash = Annotated[str, StringConstraints(pattern=r"^[0-9a-fA-F]{64}$", to_lower=True)]
RevisionSHA = Annotated[str, StringConstraints(pattern=r"^(?:[0-9a-fA-F]{40}|[0-9a-fA-F]{64})$", to_lower=True)]
Count = Annotated[int, Field(ge=0, strict=True)]

_CODE_EVIDENCE = frozenset({
    EvidenceKind.SOURCE, EvidenceKind.HISTORICAL, EvidenceKind.EXECUTION, EvidenceKind.STATIC_PROOF,
})
_HEAD_BEHAVIOR_EVIDENCE = frozenset({
    EvidenceKind.SOURCE, EvidenceKind.CONTRACT, EvidenceKind.EXECUTION, EvidenceKind.STATIC_PROOF,
})
_RESOLVED_ASSESSMENTS = frozenset({RequirementStatus.VERIFIED, RequirementStatus.VIOLATED})
_RESOLVED_INVESTIGATIONS = frozenset({InvestigationStatus.CONFIRMED, InvestigationStatus.DISPROVED})


def _unique_ids(values: Iterable[str], label: str) -> set[str]:
    seen: set[str] = set()
    for value in values:
        if value in seen:
            raise ValueError(f"duplicate {label}: {value}")
        seen.add(value)
    return seen


def _unique_references(values: tuple[str, ...]) -> tuple[str, ...]:
    _unique_ids(values, "reference")
    return values


Refs = Annotated[tuple[NonBlank, ...], AfterValidator(_unique_references)]


class IntentSource(DomainRecord):
    """One captured source of developer intent."""

    id: NonBlank
    kind: SourceKind = Field(validation_alias=AliasChoices("kind", "source_type"))
    source_ref: NonBlank
    content_hash: ContentHash
    revision: NonBlank | None = None
    captured_at: AwareDatetime | None = None
    authority_level: Literal["authoritative", "contextual", "untrusted"] = "untrusted"
    trusted_for: Refs = ()

    @model_validator(mode="before")
    @classmethod
    def migrate_source_type(cls, value: object) -> object:
        if isinstance(value, Mapping) and "source_type" in value and "kind" not in value:
            value = dict(value)
            raw = value.pop("source_type")
            value["kind"] = {"policy": "repository_policy", "pr": "pr_description"}.get(raw, raw)
        return value

    @model_validator(mode="after")
    def require_capture_identity(self) -> Self:
        if self.revision is None and self.captured_at is None:
            raise ValueError("intent source requires a revision or captured_at")
        return self


class Requirement(DomainRecord):
    """A single independently checkable acceptance criterion."""

    id: NonBlank
    description: NonBlank
    acceptance_criterion: NonBlank
    source_refs: Refs = Field(min_length=1)
    kind: RequirementKind = RequirementKind.FUNCTIONAL
    inferred: bool = False


class RequirementAssessment(DomainRecord):
    """The review's outcome for one requirement."""

    requirement_id: NonBlank
    status: RequirementStatus = RequirementStatus.NOT_ASSESSED
    evidence_refs: Refs = Field(default=(), validation_alias=AliasChoices("evidence_refs", "evidence_ids"))
    reason: NonBlank | None = None

    @model_validator(mode="after")
    def validate_outcome(self) -> Self:
        if self.status in _RESOLVED_ASSESSMENTS and not self.evidence_refs:
            raise ValueError(f"{self.status} assessment requires evidence")
        if self.status is RequirementStatus.NOT_ASSESSED and self.evidence_refs:
            raise ValueError("not_assessed cannot cite evidence")
        if self.status is RequirementStatus.NOT_APPLICABLE and self.reason is None:
            raise ValueError("not_applicable requires a reason")
        return self


class InvestigationRecord(DomainRecord):
    """A hypothesis and its related requirements and evidence."""

    id: NonBlank
    hypothesis: NonBlank
    status: InvestigationStatus = InvestigationStatus.PLANNED
    requirement_refs: Refs = ()
    claim_refs: Refs = Field(default=(), validation_alias=AliasChoices("claim_refs", "claim_ids"))
    evidence_refs: Refs = Field(default=(), validation_alias=AliasChoices("evidence_refs", "evidence_ids"))
    reason: NonBlank | None = None

    @model_validator(mode="after")
    def require_resolution_evidence(self) -> Self:
        if self.status in _RESOLVED_INVESTIGATIONS and not self.evidence_refs:
            raise ValueError(f"{self.status} investigation requires evidence")
        return self


class EvidenceRecord(DomainRecord):
    """Content-addressed evidence with explicit direction for each claim."""

    id: NonBlank
    kind: EvidenceKind
    source_ref: NonBlank
    content_hash: ContentHash
    revision_sha: RevisionSHA | None = None
    revision_side: RevisionSide | None = None
    supports_claim_refs: Refs = Field(default=(), validation_alias=AliasChoices("supports_claim_refs", "supports_claim_ids"))
    contradicts_claim_refs: Refs = Field(default=(), validation_alias=AliasChoices("contradicts_claim_refs", "contradicts_claim_ids"))
    limitations: tuple[NonBlank, ...] = ()
    observation_refs: Refs = ()

    @model_validator(mode="after")
    def validate_provenance(self) -> Self:
        has_revision = self.revision_sha is not None
        has_side = self.revision_side is not None
        if has_revision != has_side or (self.kind in _CODE_EVIDENCE and not has_revision):
            raise ValueError("evidence requires both a revision SHA and a revision side")
        if set(self.supports_claim_refs).intersection(self.contradicts_claim_refs):
            raise ValueError("evidence cannot both support and contradict the same claim")
        return self

    @property
    def is_head_behavior_evidence(self) -> bool:
        return self.revision_side is RevisionSide.HEAD and self.kind in _HEAD_BEHAVIOR_EVIDENCE


class RequirementCoverage(DomainRecord):
    """Outcome counts for a set of requirements."""

    total: Count = 0
    verified: Count = 0
    violated: Count = 0
    unverified: Count = 0
    not_assessed: Count = 0
    not_applicable: Count = 0

    @model_validator(mode="after")
    def validate_counts(self) -> Self:
        if self.assessed + self.not_assessed + self.not_applicable != self.total:
            raise ValueError("requirement coverage outcomes must add up to total")
        return self

    @computed_field
    @property
    def assessed(self) -> int:
        return self.verified + self.violated + self.unverified

    @computed_field
    @property
    def applicable(self) -> int:
        return self.total - self.not_applicable

    @computed_field
    @property
    def ratio(self) -> float | None:
        """Share of applicable requirements for which verification was attempted."""
        return self.assessed / self.applicable if self.applicable else None


def _require_known(refs: Iterable[str], known: Iterable[str], label: str, owner: str) -> None:
    missing = set(refs).difference(known)
    if missing:
        raise ValueError(f"{owner}: unknown {label}: {', '.join(sorted(missing))}")


def _require_directional_evidence(
    evidence: Mapping[str, EvidenceRecord],
    refs: Refs,
    claim_id: str,
    owner: str,
    *,
    contradicts: bool,
    head_only: bool = False,
) -> None:
    for ref in refs:
        item = evidence[ref]
        if head_only and not item.is_head_behavior_evidence:
            continue
        claim_refs = item.contradicts_claim_refs if contradicts else item.supports_claim_refs
        if claim_id in claim_refs:
            return
    direction = "contradicting" if contradicts else "supporting"
    revision = " HEAD" if head_only else ""
    raise ValueError(f"{owner} requires {direction}{revision} evidence")


def validate_investigation_evidence(
    investigation: InvestigationRecord, evidence: Mapping[str, EvidenceRecord],
) -> None:
    """Shared resolution rule for both domain knowledge and canonical results."""
    if investigation.status not in _RESOLVED_INVESTIGATIONS:
        return
    claims = {investigation.id, *investigation.claim_refs}
    contradicts = investigation.status == InvestigationStatus.DISPROVED
    for ref in investigation.evidence_refs:
        item = evidence[ref]
        direction = item.contradicts_claim_refs if contradicts else item.supports_claim_refs
        if claims.intersection(direction):
            return
    direction_name = "contradicting" if contradicts else "supporting"
    raise ValueError(f"investigation {investigation.id} requires {direction_name} evidence")


class ReviewKnowledge(DomainRecord):
    """The revision-bound domain records for one review."""

    base_sha: RevisionSHA | None = None
    head_sha: RevisionSHA | None = None
    intent_sources: tuple[IntentSource, ...] = ()
    requirements: tuple[Requirement, ...] = ()
    investigations: tuple[InvestigationRecord, ...] = ()
    evidence: tuple[EvidenceRecord, ...] = ()
    assessments: tuple[RequirementAssessment, ...] = ()

    @model_validator(mode="after")
    def validate_references(self) -> Self:
        source_ids = _unique_ids((item.id for item in self.intent_sources), "intent source ID")
        requirement_ids = _unique_ids((item.id for item in self.requirements), "requirement ID")
        investigation_ids = _unique_ids((item.id for item in self.investigations), "investigation ID")
        claim_ids = _unique_ids((*requirement_ids, *investigation_ids), "claim ID")
        _unique_ids((item.requirement_id for item in self.assessments), "assessment")
        _unique_ids((item.id for item in self.evidence), "evidence ID")
        evidence = {item.id: item for item in self.evidence}

        for requirement in self.requirements:
            _require_known(requirement.source_refs, source_ids, "intent source", f"requirement {requirement.id}")

        for item in self.evidence:
            owner = f"evidence {item.id}"
            _require_known((*item.supports_claim_refs, *item.contradicts_claim_refs), claim_ids, "claim", owner)
            if item.revision_side is not None:
                expected = self.head_sha if item.revision_side is RevisionSide.HEAD else self.base_sha
                if item.revision_sha != expected:
                    raise ValueError(f"{owner} does not match the reviewed {item.revision_side} revision")

        for investigation in self.investigations:
            owner = f"investigation {investigation.id}"
            _require_known(investigation.requirement_refs, requirement_ids, "requirement", owner)
            _require_known(investigation.claim_refs, claim_ids, "claim", owner)
            _require_known(investigation.evidence_refs, evidence, "evidence", owner)
            validate_investigation_evidence(investigation, evidence)

        for assessment in self.assessments:
            owner = f"assessment for {assessment.requirement_id}"
            _require_known((assessment.requirement_id,), requirement_ids, "requirement", owner)
            _require_known(assessment.evidence_refs, evidence, "evidence", owner)
            if assessment.status in _RESOLVED_ASSESSMENTS:
                _require_directional_evidence(
                    evidence, assessment.evidence_refs, assessment.requirement_id, owner,
                    contradicts=assessment.status is RequirementStatus.VIOLATED, head_only=True,
                )
        return self

    @property
    def requirement_coverage(self) -> RequirementCoverage:
        """Derive coverage from assessments, including requirements without one."""
        counts = Counter(assessment.status for assessment in self.assessments)
        missing_assessments = len(self.requirements) - len(self.assessments)
        return RequirementCoverage(
            total=len(self.requirements),
            verified=counts[RequirementStatus.VERIFIED],
            violated=counts[RequirementStatus.VIOLATED],
            unverified=counts[RequirementStatus.UNVERIFIED],
            not_assessed=counts[RequirementStatus.NOT_ASSESSED] + missing_assessments,
            not_applicable=counts[RequirementStatus.NOT_APPLICABLE],
        )
