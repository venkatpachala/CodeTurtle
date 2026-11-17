"""Stage 01.1 domain contracts. These tests use no review runtime or services."""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from core.domain.review_contracts import (
    EvidenceKind,
    EvidenceRecord,
    IntentSource,
    InvestigationRecord,
    InvestigationStatus,
    Requirement,
    RequirementAssessment,
    RequirementCoverage,
    RequirementStatus,
    ReviewKnowledge,
    RevisionSide,
    SourceKind,
)

BASE_SHA = "a" * 40
HEAD_SHA = "b" * 40
DIGEST = "c" * 64


def make_source(**changes) -> IntentSource:
    return IntentSource(**{
        "id": "SRC-001",
        "kind": SourceKind.ISSUE,
        "source_ref": "owner/repo#128",
        "content_hash": DIGEST,
        "captured_at": "2026-11-17T10:00:00Z",
        **changes,
    })


def make_requirement(**changes) -> Requirement:
    return Requirement(**{
        "id": "REQ-001",
        "description": "Cap retry attempts",
        "acceptance_criterion": "A retryable operation makes at most three attempts.",
        "source_refs": ("SRC-001",),
        **changes,
    })


def make_evidence(**changes) -> EvidenceRecord:
    return EvidenceRecord(**{
        "id": "EVD-001",
        "kind": EvidenceKind.STATIC_PROOF,
        "source_ref": "retry.py:17-21",
        "content_hash": DIGEST,
        "revision_side": RevisionSide.HEAD,
        "revision_sha": HEAD_SHA,
        "supports_claim_refs": ("REQ-001", "INV-001"),
        **changes,
    })


def make_investigation(**changes) -> InvestigationRecord:
    return InvestigationRecord(**{
        "id": "INV-001",
        "hypothesis": "A retryable operation exits after the third attempt.",
        "status": InvestigationStatus.CONFIRMED,
        "requirement_refs": ("REQ-001",),
        "evidence_refs": ("EVD-001",),
        **changes,
    })


def make_knowledge(**changes) -> ReviewKnowledge:
    return ReviewKnowledge(**{
        "base_sha": BASE_SHA,
        "head_sha": HEAD_SHA,
        "intent_sources": (make_source(),),
        "requirements": (make_requirement(),),
        "investigations": (make_investigation(),),
        "evidence": (make_evidence(),),
        "assessments": (
            RequirementAssessment(
                requirement_id="REQ-001",
                status=RequirementStatus.VERIFIED,
                evidence_refs=("EVD-001",),
            ),
        ),
        **changes,
    })


def test_valid_knowledge_has_independent_outcomes():
    knowledge = make_knowledge()
    assert knowledge.requirement_coverage.verified == 1
    assert knowledge.requirement_coverage.ratio == 1
    assert knowledge.investigations[0].status is InvestigationStatus.CONFIRMED
    assert knowledge.assessments[0].status is RequirementStatus.VERIFIED

    incomplete = RequirementAssessment(
        requirement_id="REQ-001", status=RequirementStatus.UNVERIFIED,
        reason="Retry behavior is unknown for a caller outside the changed code.",
    )
    knowledge = make_knowledge(assessments=(incomplete,))
    assert knowledge.investigations[0].status is InvestigationStatus.CONFIRMED
    assert knowledge.requirement_coverage.unverified == 1
    assert knowledge.requirement_coverage.verified == 0


def test_violated_without_evidence_rejected():
    for status in (RequirementStatus.VIOLATED, RequirementStatus.VERIFIED):
        with pytest.raises(ValidationError, match="requires evidence"):
            RequirementAssessment(requirement_id="REQ-001", status=status)


def test_not_assessed_cannot_claim_evidence():
    with pytest.raises(ValidationError, match="not_assessed cannot cite evidence"):
        RequirementAssessment(
            requirement_id="REQ-001",
            status=RequirementStatus.NOT_ASSESSED,
            evidence_refs=("EVD-001",),
        )
    with pytest.raises(ValidationError, match="not_applicable requires a reason"):
        RequirementAssessment(requirement_id="REQ-001", status=RequirementStatus.NOT_APPLICABLE)


def test_unassessed_requirements_counted():
    coverage = make_knowledge(assessments=()).requirement_coverage
    assert coverage.total == 1
    assert coverage.not_assessed == 1
    assert coverage.assessed == 0
    assert coverage.ratio == 0
    assert ReviewKnowledge().requirement_coverage.ratio is None

    out_of_scope = RequirementAssessment(
        requirement_id="REQ-002", status=RequirementStatus.NOT_APPLICABLE,
        reason="The change does not implement the optional cloud provider.",
    )
    verified = make_knowledge().assessments[0]
    coverage = make_knowledge(
        requirements=(make_requirement(), make_requirement(id="REQ-002")),
        assessments=(verified, out_of_scope),
    ).requirement_coverage
    assert coverage.total == 2
    assert coverage.not_applicable == 1
    assert coverage.applicable == coverage.assessed == 1
    assert coverage.ratio == 1

    primary_out_of_scope = RequirementAssessment(
        requirement_id="REQ-001", status=RequirementStatus.NOT_APPLICABLE,
        reason="This run evaluates a separate operating mode.",
    )
    coverage = make_knowledge(assessments=(primary_out_of_scope,)).requirement_coverage
    assert coverage.applicable == 0
    assert coverage.ratio is None
    with pytest.raises(ValidationError, match="add up to total"):
        RequirementCoverage(total=1, verified=1, violated=1)


def test_duplicate_requirements_rejected():
    with pytest.raises(ValidationError, match="duplicate requirement ID.*REQ-001"):
        make_knowledge(requirements=(make_requirement(), make_requirement()))
    with pytest.raises(ValidationError, match="duplicate assessment.*REQ-001"):
        make_knowledge(assessments=make_knowledge().assessments * 2)
    with pytest.raises(ValidationError, match="duplicate claim ID.*REQ-001"):
        make_knowledge(investigations=(make_investigation(id="REQ-001"),))
    with pytest.raises(ValidationError, match="duplicate reference"):
        make_requirement(source_refs=("SRC-001", "SRC-001"))


def test_investigation_cannot_reference_missing_requirement():
    inv = InvestigationRecord(
        id="INV-001",
        hypothesis="Retries execute four times",
        requirement_refs=("MISSING",),
        status=InvestigationStatus.PLANNED,
    )
    with pytest.raises(ValidationError, match="unknown requirement.*MISSING"):
        make_knowledge(investigations=(inv,))
    unresolved = make_investigation(status=InvestigationStatus.UNRESOLVED, evidence_refs=())
    assert make_knowledge(investigations=(unresolved,)).investigations[0] == unresolved
    dangling_ref = make_investigation(status=InvestigationStatus.UNRESOLVED, evidence_refs=("MISSING",))
    with pytest.raises(ValidationError, match="unknown evidence.*MISSING"):
        make_knowledge(investigations=(dangling_ref,))


def test_round_trip_serialization():
    original = make_knowledge()
    serialized = original.model_dump(mode="json")
    restored = ReviewKnowledge.model_validate(json.loads(json.dumps(serialized)))
    assert restored == original
    assert serialized["requirements"][0]["id"] == "REQ-001"
    assert serialized["intent_sources"][0]["captured_at"] == "2026-11-17T10:00:00Z"
    assert serialized["assessments"][0]["evidence_refs"] == ["EVD-001"]
    assert restored.assessments[0].evidence_refs == ("EVD-001",)


def test_domain_record_is_frozen():
    source = make_source()
    knowledge = make_knowledge()
    with pytest.raises(ValidationError, match="frozen"):
        source.id = "SRC-999"
    with pytest.raises(ValidationError, match="frozen"):
        knowledge.intent_sources += (source,)
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        make_source(unexpected=True)
    with pytest.raises(ValidationError, match="revision or captured_at"):
        make_source(captured_at=None)
    with pytest.raises(ValidationError):
        make_source(captured_at="2026-11-17T10:00:00")
    with pytest.raises(ValidationError):
        make_source(content_hash="not-a-digest")


def test_requirement_source_and_evidence_references_resolve():
    with pytest.raises(ValidationError, match="unknown intent source.*SRC-001"):
        make_knowledge(intent_sources=())
    broken = RequirementAssessment(
        requirement_id="REQ-001", status=RequirementStatus.VERIFIED, evidence_refs=("MISSING",),
    )
    with pytest.raises(ValidationError, match="unknown evidence.*MISSING"):
        make_knowledge(assessments=(broken,))
    unknown_requirement = RequirementAssessment(requirement_id="MISSING")
    with pytest.raises(ValidationError, match="unknown requirement.*MISSING"):
        make_knowledge(assessments=(unknown_requirement,))
    with pytest.raises(ValidationError, match="unknown claim.*MISSING"):
        make_knowledge(evidence=(make_evidence(supports_claim_refs=("MISSING",)),))


def test_revision_bound_evidence_maps_to_exact_review_side():
    with pytest.raises(ValidationError, match="both.*revision"):
        make_evidence(revision_side=None, revision_sha=None)
    with pytest.raises(ValidationError, match="reviewed head"):
        make_knowledge(evidence=(make_evidence(revision_sha=BASE_SHA),))
    with pytest.raises(ValidationError, match="reviewed head"):
        make_knowledge(head_sha=None)

    historical = make_evidence(kind=EvidenceKind.HISTORICAL, revision_side=RevisionSide.BASE, revision_sha=BASE_SHA)
    assert make_knowledge(
        evidence=(historical,), assessments=(), investigations=(make_investigation(),),
    ).evidence == (historical,)
    with pytest.raises(ValidationError, match="supporting HEAD evidence"):
        make_knowledge(evidence=(historical,))
    bypassed_validator = make_evidence().model_copy(update={"revision_sha": None})
    with pytest.raises(ValidationError, match="both.*revision"):
        make_knowledge(evidence=(bypassed_validator,))


def test_decisive_requirement_uses_directional_head_evidence():
    assessment = RequirementAssessment(
        requirement_id="REQ-001", status=RequirementStatus.VIOLATED, evidence_refs=("EVD-001",),
    )
    with pytest.raises(ValidationError, match="contradicting HEAD evidence"):
        make_knowledge(assessments=(assessment,))
    refutation = make_evidence(supports_claim_refs=("INV-001",), contradicts_claim_refs=("REQ-001",))
    assert make_knowledge(evidence=(refutation,), assessments=(assessment,)).requirement_coverage.violated == 1

    inference = make_evidence(kind=EvidenceKind.MODEL_INFERENCE)
    with pytest.raises(ValidationError, match="supporting HEAD evidence"):
        make_knowledge(evidence=(inference,))
    with pytest.raises(ValidationError, match="cannot both support and contradict"):
        make_evidence(contradicts_claim_refs=("REQ-001",))


def test_investigation_resolution_has_own_evidence():
    with pytest.raises(ValidationError, match="confirmed.*requires evidence"):
        make_investigation(evidence_refs=())
    unrelated_to_hypothesis = make_evidence(supports_claim_refs=("REQ-001",))
    with pytest.raises(ValidationError, match="investigation INV-001.*supporting evidence"):
        make_knowledge(evidence=(unrelated_to_hypothesis,))
    disproved = make_investigation(status=InvestigationStatus.DISPROVED)
    disproof = make_evidence(supports_claim_refs=("REQ-001",), contradicts_claim_refs=("INV-001",))
    knowledge = make_knowledge(evidence=(disproof,), investigations=(disproved,))
    assert knowledge.investigations[0].status is InvestigationStatus.DISPROVED
    assert knowledge.requirement_coverage.verified == 1
