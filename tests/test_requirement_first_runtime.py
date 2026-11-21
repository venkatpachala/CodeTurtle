"""New requirement candidates still pass normal proof, positioning and verifier gates."""
import json
from types import SimpleNamespace

from core.runtime.models import ReviewResult
from core.runtime.review_runtime import ReviewRuntime
from tests.test_requirement_investigator import requirement_case, decision_for
from tests.test_input_snapshot import repository


def run_case(requirement_case, *, verdict="VERIFIED", outcome="violated", strategy="investigate", static=False):
    provider, snapshot, intent = requirement_case
    def complete(stage, prompt):
        return json.dumps(decision_for(prompt, outcome))
    context = SimpleNamespace(
        review_snapshot=snapshot, input_provider=provider, review_intent=intent,
        requirement_strategy=strategy, analysis_mode="static_only" if static else "model",
        pr_head_sha=snapshot.head_sha, pr_base_sha=snapshot.base_sha,
        files_changed=["app.py"], full_diff=provider.diff(snapshot),
    )
    return ReviewRuntime(llm=lambda _: "[]", verification_llm=lambda _: verdict,
                         requirement_llm=complete).run(context)


def test_requirement_investigation_detects_beyond_empty_discovery(requirement_case):
    result = run_case(requirement_case)
    assert len(result.product_findings) == 1
    assert result.product_findings[0].source == "agent"
    assert result.product_findings[0].hypothesis_id.startswith("IR-")
    assert result.requirement_assessments[0].status == "violated"
    assert result.source_observations
    assert result.evidence[0].observation_refs
    assert result.decision == "REQUEST_CHANGES"
    assert ReviewResult.from_dict(result.to_dict()).to_dict() == result.to_dict()


def test_downstream_disproof_prevents_requirement_promotion(requirement_case):
    result = run_case(requirement_case, verdict="DISPROVED")
    assert result.product_findings == []
    assert result.requirement_assessments[0].status == "unverified"
    assert result.investigations[0].status == "unresolved"
    assert result.source_observations
    assert result.evidence == []


def test_supported_requirement_is_bounded_and_does_not_imply_inspection(requirement_case):
    # Scripted agreement tests the mechanism; it is not a correctness label for this fixture.
    result = run_case(requirement_case, outcome="satisfied")
    assert result.product_findings == []
    assert result.requirement_assessments[0].status == "verified"
    assert "Bounded source assessment" in result.requirement_assessments[0].reason
    assert result.investigations[0].status == "disproved"
    assert result.inspection.inspected == 0
    assert not result.approval_eligible


def test_static_only_and_off_modes_never_claim_requirement_assessment(requirement_case):
    for options in ({"static": True}, {"strategy": "off"}):
        result = run_case(requirement_case, **options)
        assert result.requirement_assessments[0].status == "not_assessed"
        assert result.provenance["requirement_runs"][0]["attempted"] is False
        assert result.source_observations == []


def test_link_ablation_cannot_find_this_defect_from_empty_discovery(requirement_case):
    result = run_case(requirement_case, strategy="link")
    assert result.product_findings == []
    assert result.requirement_assessments[0].status == "unverified"
