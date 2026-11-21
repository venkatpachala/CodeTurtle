"""Stage 01 wire compatibility and evidence-linked domain invariants."""

from __future__ import annotations

import json
from dataclasses import replace

import pytest
from pydantic import ValidationError

from benchmark.evaluator import evaluate_pr
from cli.commands.review import ReviewPipeline
from core.review.contract import ReviewHealth, ReviewTarget
from core.domain.review_contracts import RevisionSide
from core.review.finding import ExecutionEvidence, ReviewFinding
from core.review.requirements import (
    EvidenceRecord,
    IntentSource,
    InvestigationRecord,
    Requirement,
    RequirementAssessment,
    RequirementCoverage,
)
from core.review.timing import TimingRecord
from core.review.trace import PipelineTrace
from core.runtime.models import Bundle, Comment, ReviewResult

BASE = "a" * 40
HEAD = "b" * 40
DIGEST = "c" * 64


@pytest.fixture
def linked_review():
    return ReviewResult(
        target=ReviewTarget(base_sha=BASE, head_sha=HEAD),
        intent_sources=[
            IntentSource(
                id="S1", source_type="task", source_ref="task.md",
                content_hash=DIGEST, revision="task-v1",
            ),
        ],
        requirements=[
            Requirement(
                id="R1", description="Cap retries", source_refs=("S1",),
                acceptance_criterion="A retryable operation makes at most three attempts.",
            ),
            Requirement(
                id="R2", description="Skip auth retries", source_refs=("S1",),
                acceptance_criterion="A permanent auth failure makes one attempt.",
            ),
        ],
        requirement_assessments=[
            RequirementAssessment(requirement_id="R1", status="verified", evidence_refs=("E1",)),
        ],
        evidence=[
            EvidenceRecord(
                id="E1", kind="static_proof", source_ref="retry.py:17", content_hash=DIGEST,
                revision_sha=HEAD, revision_side="head", supports_claim_refs=("R1",),
            ),
        ],
        investigations=[
            InvestigationRecord(id="I1", hypothesis="Auth failures may retry", status="unresolved",
                                claim_refs=("R2",)),
        ],
    )


def test_v21_defaults_are_additive():
    data = ReviewResult().to_dict()
    assert data["schema_version"] == "2.1"
    for field in ("intent_sources", "requirements", "requirement_assessments", "investigations", "evidence"):
        assert data[field] == []
    assert data["requirement_coverage"]["total"] == 0
    assert data["requirement_coverage"]["ratio"] is None
    assert data["inspection"]["ratio"] is None
    assert data["decision"] == "COMMENT"


def test_coverage_is_derived_separately_from_inspection(linked_review):
    data = linked_review.to_dict()
    assert data["requirement_coverage"] == {
        "total": 2, "verified": 1, "violated": 0, "unverified": 0,
        "not_assessed": 1, "not_applicable": 0, "applicable": 2, "assessed": 1, "ratio": 0.5,
    }
    assert data["inspection"]["ratio"] is None
    assert data["investigations"][0]["status"] == "unresolved"
    assert data["investigations"][0]["evidence_refs"] == []
    assert ReviewResult.from_dict(json.loads(json.dumps(data))).to_dict() == data


def test_intent_provenance_has_immutable_capture_identity():
    fields = dict(id="S1", source_type="issue", source_ref="owner/repo#1", content_hash=DIGEST)
    with pytest.raises(ValidationError, match="revision or captured_at"):
        IntentSource(**fields)
    with pytest.raises(ValidationError):
        IntentSource(**fields, captured_at="2026-11-17T10:00:00")
    source = IntentSource(**fields, captured_at="2026-11-17T10:00:00Z")
    with pytest.raises(ValidationError, match="frozen"):
        source.source_ref = "changed"
    payload = ReviewResult(intent_sources=[source]).to_dict()
    assert payload["intent_sources"][0]["captured_at"] == "2026-11-17T10:00:00Z"
    assert ReviewResult.from_dict(payload).intent_sources == [source]


def test_reference_integrity(linked_review):
    with pytest.raises(ValueError, match="unknown intent source.*S1"):
        replace(linked_review, intent_sources=[])
    with pytest.raises(ValueError, match="unknown evidence.*E1"):
        replace(linked_review, evidence=[])
    with pytest.raises(ValueError, match="duplicate requirement ID.*R1"):
        replace(linked_review, requirements=linked_review.requirements * 2)
    unlinked = linked_review.evidence[0].model_copy(update={"supports_claim_refs": ("missing",)})
    with pytest.raises(ValueError, match="unknown claim.*missing"):
        replace(linked_review, evidence=[unlinked])


def test_code_evidence_requires_explicit_review_revision(linked_review):
    with pytest.raises(ValidationError, match="revision"):
        EvidenceRecord(id="E2", kind="source", source_ref="retry.py", content_hash=DIGEST)
    evidence = linked_review.evidence[0]
    wrong_revision = evidence.model_copy(update={"revision_sha": BASE})
    with pytest.raises(ValueError, match="reviewed head"):
        replace(linked_review, evidence=[wrong_revision])

    base_evidence = evidence.model_copy(update={"revision_side": RevisionSide.BASE, "revision_sha": BASE})
    with pytest.raises(ValueError, match="supporting evidence"):
        replace(linked_review, evidence=[base_evidence])
    historical_context = replace(linked_review, evidence=[base_evidence], requirement_assessments=[])
    assert historical_context.to_dict()["evidence"][0]["revision_sha"] == BASE


@pytest.mark.parametrize("status", ["verified", "violated"])
def test_conclusive_assessment_requires_directional_behavior_evidence(linked_review, status):
    with pytest.raises(ValidationError, match="requires evidence"):
        RequirementAssessment(requirement_id="R1", status=status)
    assessment = RequirementAssessment(requirement_id="R1", status=status, evidence_refs=("E1",))
    evidence = linked_review.evidence[0]
    text_only = EvidenceRecord(
        id="E1", kind="requirement", source_ref="task.md", content_hash=DIGEST,
        supports_claim_refs=("R1",) if status == "verified" else (),
        contradicts_claim_refs=("R1",) if status == "violated" else (),
    )
    with pytest.raises(ValueError, match="evidence"):
        replace(linked_review, requirement_assessments=[assessment], evidence=[text_only])
    if status == "violated":
        with pytest.raises(ValueError, match="contradicting evidence"):
            replace(linked_review, requirement_assessments=[assessment])
        evidence = evidence.model_copy(
            update={"supports_claim_refs": (), "contradicts_claim_refs": ("R1",)},
        )
    data = replace(linked_review, requirement_assessments=[assessment], evidence=[evidence]).to_dict()
    assert data["requirement_coverage"][status] == 1


def test_coverage_rejects_impossible_counts():
    with pytest.raises(ValidationError, match="add up to total"):
        RequirementCoverage(total=1, verified=1, violated=1)


def test_pending_assessments_and_duplicate_assessments(linked_review):
    with pytest.raises(ValidationError, match="not_assessed"):
        RequirementAssessment(requirement_id="R2", status="not_assessed", evidence_refs=("E1",))
    with pytest.raises(ValueError, match="duplicate assessment.*R1"):
        replace(linked_review, requirement_assessments=linked_review.requirement_assessments * 2)
    unknown = RequirementAssessment(requirement_id="missing", status="unverified")
    with pytest.raises(ValueError, match="unknown requirement.*missing"):
        replace(linked_review, requirement_assessments=[unknown])
    incomplete = RequirementAssessment(requirement_id="R2", status="unverified", reason="missing caller")
    data = replace(linked_review, requirement_assessments=[incomplete]).to_dict()
    assert data["requirement_coverage"]["assessed"] == 1
    assert data["requirement_coverage"]["unverified"] == 1


def test_finding_links_and_unresolved_investigation_are_checked(linked_review):
    finding = ReviewFinding(
        id="F1", title="Auth is retried", claim="Auth failure enters the retry loop",
        file="retry.py", line=17, verification_status="verified", hypothesis_id="I1",
    )
    with pytest.raises(ValueError, match="requires a confirmed investigation"):
        replace(linked_review, findings=[finding])
    by_claim = linked_review.investigations[0].model_copy(update={"claim_refs": ("F1",)})
    with pytest.raises(ValueError, match="requires a confirmed investigation"):
        replace(linked_review, investigations=[by_claim], findings=[replace(finding, hypothesis_id=None)])
    with pytest.raises(ValueError, match="unknown evidence.*absent"):
        replace(linked_review, findings=[replace(finding, hypothesis_id=None, evidence_ids=["absent"])])

    # Recheck the result at the product boundary after in-memory changes.
    linked_review.findings.append(finding)
    with pytest.raises(ValueError, match="confirmed investigation"):
        _ = linked_review.product_findings


def test_confirmed_investigation_can_link_a_verified_finding(linked_review):
    finding = ReviewFinding(
        id="F1", title="Auth is retried", claim="Auth failure enters the retry loop",
        file="retry.py", line=17, verification_status="verified", hypothesis_id="I1", evidence_ids=["E1"],
    )
    evidence = linked_review.evidence[0].model_copy(update={"supports_claim_refs": ("R1", "F1")})
    investigation = InvestigationRecord(
        id="I1", hypothesis="Auth failures retry", status="confirmed",
        claim_refs=("F1",), evidence_refs=("E1",),
    )
    result = replace(linked_review, findings=[finding], investigations=[investigation], evidence=[evidence])
    assert result.to_dict()["product_findings"][0]["evidence_ids"] == ["E1"]
    with pytest.raises(ValueError, match="verified finding F1 requires supporting evidence"):
        replace(result, findings=[replace(finding, evidence_ids=[])])


def test_legacy_payload_upgrades_with_no_loss_of_review_data():
    trace = PipelineTrace()
    candidate_id = trace.next_candidate_id()
    trace.keep(candidate_id, "final", line=1)
    review = ReviewResult(
        findings=[ReviewFinding(
            id="F1", title="Title", claim="Claim", file="app.py", line=1,
            verification_status="verified", evidence=["app.py#L1"],
            execution=ExecutionEvidence(status="FAILED", exit_code=1, failed=1),
        )],
        bundles=[Bundle(id="B1", units=[{"id": "CU-001"}])],
        comments=[Comment(bundle_id="B1", file="app.py")],
        pipeline_trace=trace, timing=TimingRecord(total_s=1.5), decision="REQUEST_CHANGES",
    )
    current = review.to_dict()
    additions = {"intent_sources", "requirements", "requirement_assessments", "investigations",
                 "evidence", "requirement_coverage"}
    old = {key: value for key, value in current.items() if key not in additions}
    old["schema_version"] = "2.0"
    migrated = ReviewResult.from_dict({"schema_version": "2.0", "result": old})
    assert migrated.to_dict() == current
    assert migrated.pipeline_trace.summary() == trace.summary()
    assert old["schema_version"] == "2.0"
    with pytest.raises(ValueError, match="unsupported.*schema"):
        ReviewResult.from_dict({**old, "schema_version": "3.0"})
    with pytest.raises(ValueError, match="requirement_coverage"):
        ReviewResult.from_dict({**current, "requirement_coverage": {"total": 99}})


@pytest.mark.parametrize("status", ["failed", "skipped"])
def test_null_decision_survives_cli_and_legacy_adapter(tmp_path, status):
    output = tmp_path / "failure.json"
    pipeline = ReviewPipeline()
    pipeline._write_failure_json(str(output), "fixture", skipped=status == "skipped")
    data = json.loads(output.read_text(encoding="utf-8"))
    assert data["schema_version"] == "2.1"
    assert data["decision"] is None
    assert data["health"]["status"] == status
    assert data["review_comments"] == []
    assert ReviewResult.from_dict(data).decision is None
    old = {**data, "schema_version": "2.0"}
    assert ReviewResult.from_dict(old).to_dict()["decision"] is None


def test_cli_diagnostics_and_benchmark_product_output_stay_separate(tmp_path):
    finding = ReviewFinding(id="F1", title="Maybe", claim="Possible retry issue", file="retry.py", line=17,
                            verification_status="uncertain")
    result = ReviewResult(decision=None, health=ReviewHealth(status="partial"), findings=[finding])
    pipeline = ReviewPipeline()
    pipeline.context.final_state = {"_review_result": result}
    path = tmp_path / "review.json"
    pipeline._write_benchmark_json(str(path))
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["schema_version"] == "2.1"
    assert data["decision"] is None
    assert data["findings"] == data["review_comments"] == []
    assert data["diagnostic_findings"] == [finding.to_dict()]
    assert data["result"]["requirement_coverage"]["total"] == 0
    assert ReviewResult.from_dict(data).to_dict() == result.to_dict()
    assert evaluate_pr(data["result"], [])["fp"] == 0
    for version in ("2.0", "2.1"):
        deliberately_empty = {**data, "schema_version": version, "review_comments": [finding.to_dict()]}
        assert evaluate_pr(deliberately_empty, [])["fp"] == 0
