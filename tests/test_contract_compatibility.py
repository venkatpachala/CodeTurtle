"""Canonical contracts, legacy input migration, and coverage semantics."""
from dataclasses import replace

import pytest

from core.domain import review_contracts as domain
from core.review import requirements as compatibility
from core.runtime.models import ReviewResult


def test_compatibility_imports_are_the_same_classes():
    for name in compatibility.__all__:
        assert getattr(compatibility, name) is getattr(domain, name)


def test_legacy_record_names_load_without_parallel_models():
    source = domain.IntentSource(
        id="S1", source_type="policy", source_ref="policy.json",
        content_hash="a" * 64, revision="v1",
    )
    assert source.kind is domain.SourceKind.REPOSITORY_POLICY
    assessment = domain.RequirementAssessment(
        requirement_id="R1", status="unverified", evidence_ids=("E1",),
    )
    assert assessment.evidence_refs == ("E1",)
    evidence = domain.EvidenceRecord(
        id="E1", kind="model_inference", source_ref="request-1", content_hash="b" * 64,
        supports_claim_ids=("R1",),
    )
    assert evidence.supports_claim_refs == ("R1",)


def test_not_applicable_and_not_assessed_have_different_denominators():
    source = domain.IntentSource(
        id="S1", kind="task", source_ref="task", content_hash="a" * 64, revision="v1",
    )
    requirement = domain.Requirement(
        id="R1", description="Optional API", acceptance_criterion="API is enabled",
        source_refs=("S1",),
    )
    review = ReviewResult(intent_sources=[source], requirements=[requirement])
    assert review.requirement_coverage.not_assessed == 1
    assert review.requirement_coverage.ratio == 0
    review = replace(review, requirement_assessments=[domain.RequirementAssessment(
        requirement_id="R1", status="not_applicable", reason="CLI-only scope",
    )])
    assert review.requirement_coverage.not_applicable == 1
    assert review.requirement_coverage.ratio is None
    assert ReviewResult.from_dict(review.to_dict()).to_dict() == review.to_dict()


def test_old_v21_coverage_without_new_derived_fields_still_loads():
    data = ReviewResult().to_dict()
    for key in ("not_applicable", "applicable"):
        data["requirement_coverage"].pop(key)
    assert ReviewResult.from_dict(data).requirement_coverage.ratio is None


def test_runtime_checks_investigation_requirement_links():
    investigation = domain.InvestigationRecord(
        id="I1", hypothesis="Missing invariant", requirement_refs=("missing",),
    )
    with pytest.raises(ValueError, match="unknown requirement"):
        ReviewResult(investigations=[investigation])
