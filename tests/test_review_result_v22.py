"""Canonical artifacts preserve observations and share investigation resolution rules."""
from dataclasses import replace

import pytest

from core.domain.review_contracts import EvidenceRecord, InvestigationRecord, ReviewKnowledge
from core.intent.observations import collect_observations
from core.review.contract import ReviewTarget
from core.runtime.models import ReviewResult
from tests.test_input_snapshot import repository
from core.input.snapshot import GitSnapshotProvider


def test_observations_roundtrip_and_legacy_21_upgrades(repository):
    root, base = repository
    provider = GitSnapshotProvider(root)
    snapshot = provider.resolve(base)
    observations, _ = collect_observations(provider, snapshot, ("app.py",))
    result = ReviewResult(target=ReviewTarget(base_sha=base, head_sha=snapshot.head_sha),
                          source_observations=list(observations), provenance={"snapshot_id": snapshot.id})
    assert ReviewResult.from_dict(result.to_dict()).to_dict() == result.to_dict()
    assert result.to_dict()["schema_version"] == "2.4"
    old = ReviewResult().to_dict()
    old["schema_version"] = "2.1"
    old.pop("source_observations")
    assert ReviewResult.from_dict(old).source_observations == []


def test_evidence_cannot_reference_another_revision_or_excerpt(repository):
    root, base = repository
    provider = GitSnapshotProvider(root)
    snapshot = provider.resolve(base)
    observations, _ = collect_observations(provider, snapshot, ("app.py",))
    head = observations[1]
    evidence = EvidenceRecord(id="E1", kind="source", source_ref="app.py:1",
        revision_side="head", revision_sha=snapshot.head_sha, content_hash=head.excerpt_sha256,
        observation_refs=(head.id,))
    result = ReviewResult(target=ReviewTarget(base_sha=base, head_sha=snapshot.head_sha),
                          evidence=[evidence], source_observations=list(observations))
    with pytest.raises(ValueError, match="source observation"):
        replace(result, evidence=[evidence.model_copy(update={"content_hash": "a" * 64})])
    with pytest.raises(ValueError, match="source observation"):
        replace(result, evidence=[evidence.model_copy(update={"observation_refs": (observations[0].id,)})])
    with pytest.raises(ValueError, match="snapshot"):
        replace(result, provenance={"snapshot_id": "a" * 64})


def test_both_aggregate_models_reject_unrelated_resolution_evidence():
    inv = InvestigationRecord(id="I1", hypothesis="Bug exists", status="confirmed", evidence_refs=("E1",))
    other = InvestigationRecord(id="I2", hypothesis="Another behavior")
    evidence = EvidenceRecord(id="E1", kind="model_inference", source_ref="request",
                              content_hash="a" * 64, supports_claim_refs=("I2",))
    for constructor in (ReviewKnowledge, ReviewResult):
        with pytest.raises(ValueError, match="investigation I1 requires supporting evidence"):
            constructor(investigations=[inv, other], evidence=[evidence])
