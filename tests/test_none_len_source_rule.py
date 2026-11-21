"""Narrow source semantics work without model agreement; unsupported shapes abstain."""
import json
from types import SimpleNamespace

import pytest

from core.agent.bundle_agent import AgentRunResult
from core.domain.finding_verification import FindingVerificationRecord
from core.review.budget import ReviewBudget
from core.runtime.models import ReviewResult
from core.runtime.review_runtime import ReviewRuntime
from core.verification.source_verifier import SourceFindingVerifier
from tests.test_source_finding_verifier import candidate, PROTECTED, BROKEN, verification_case
from tests.test_input_snapshot import repository


@pytest.mark.parametrize("before,after,verdict", [(PROTECTED,BROKEN,"supported"),
    (PROTECTED,PROTECTED,"refuted"),(BROKEN,BROKEN,"refuted")])
@pytest.mark.parametrize("filler", [0,300])
def test_direct_contract_is_decided_with_exact_evidence_and_no_model_request(verification_case, before, after, verdict, filler):
    prefix = "# padding\n" * filler
    provider, snapshot = verification_case(before=prefix+before, after=prefix+after)
    budget = ReviewBudget()
    verifier = SourceFindingVerifier(provider, snapshot, lambda _: pytest.fail("unneeded model call"), budget, source_rules=True)
    assert verifier.verify(candidate(), None, []) == ("VERIFIED" if verdict == "supported" else "DISPROVED")
    record = verifier.records[0]
    assert record.verification_method == "source_rule" and record.source_rule_id == "python-none-len-v1"
    assert record.verdict == verdict and record.attempts == () and budget.calls == 0
    record.validate_sources(verifier.observations)


@pytest.mark.parametrize("after", [
    "len = custom_len\n" + BROKEN,
    "@decorator\n" + BROKEN,
    "async " + BROKEN,
    "def size(items, extra=None):\n    return len(items)\n",
    "def size(items):\n    return other(items)\n",
    "def size(items):\n    print(items)\n    return len(items)\n",
    "def size(items):\n    if items is None:\n        return 1\n    return len(items)\n",
    "def size(items):\n    if other is None:\n        return 0\n    return len(items)\n",
    "def size(items):\n    return len(items or [])\n",
])
def test_unsupported_contract_shapes_continue_to_model_instead_of_inventing_proof(verification_case, after):
    provider, snapshot = verification_case(after=after)
    calls = []
    def model(prompt):
        calls.append(prompt)
        return json.dumps({"verdict":"unresolved","checked_trigger":"items is None",
            "rationale":"Unsupported contract","path_analysis":"Needs further inspection",
            "supporting_citations":[],"counter_citations":[],"missing_evidence":["contract"],"refutation_basis":"none"})
    verifier = SourceFindingVerifier(provider, snapshot, model, ReviewBudget(), source_rules=True)
    verifier.verify(candidate(), None, [])
    assert calls and verifier.records[0].verification_method == "model"
    assert verifier.records[0].verdict == "unresolved"


def test_runtime_default_source_rule_validates_a_discovered_candidate_and_roundtrips(verification_case):
    provider, snapshot = verification_case()
    class Discovery:
        def run_result(self,bundle,tools):
            c = candidate()
            c.bundle_id = bundle.id
            return AgentRunResult(status="VALID_CANDIDATES",candidates=[c])
    result = ReviewRuntime(agent=Discovery(), rule_engine=lambda *a,**k: [],
        finding_verification_llm=lambda _: pytest.fail("rule should resolve exact known contract")).run(SimpleNamespace(
            review_snapshot=snapshot,input_provider=provider,repo_dir=str(provider.root),
            pr_base_sha=snapshot.base_sha,pr_head_sha=snapshot.head_sha,
            files_changed=["app.py"],full_diff=provider.diff(snapshot)))
    assert len(result.product_findings) == 1 and result.decision == "REQUEST_CHANGES"
    assert result.finding_verifications[0].verification_method == "source_rule"
    assert ReviewResult.from_dict(result.to_dict()).to_dict() == result.to_dict()
    record = result.finding_verifications[0].model_copy(update={"source_rule_id":"fabricated-rule"})
    with pytest.raises(ValueError, match="cannot be reproduced"):
        record.validate_sources({o.id:o for o in result.source_observations})


@pytest.mark.parametrize("field,value", [("expected","1"),("actual","ValueError"),
    ("violating_condition","items is None and flag"),("symbol","Other.size"),
    ("existing_code","some other operation")])
def test_rule_never_rewrites_a_different_claim_to_fit_its_contract(verification_case, field, value):
    from core.verification.none_len_contract import verify_none_len
    from core.intent.observations import collect_observations
    provider, snapshot = verification_case()
    observations, _ = collect_observations(provider,snapshot,("app.py",))
    c = candidate()
    setattr(c,field,value)
    assert verify_none_len(c,observations) is None


@pytest.mark.parametrize("actual", ["Error", "error", " ERROR "])
def test_concrete_type_error_also_supports_generic_error_without_rewriting_claim(verification_case, actual):
    provider,snapshot = verification_case()
    c = candidate()
    c.actual = actual
    c.violating_condition = "size(None)"
    verifier = SourceFindingVerifier(provider,snapshot,lambda _:pytest.fail("unneeded call"),ReviewBudget(),source_rules=True)
    assert verifier.verify(c,None,[]) == "VERIFIED"
    assert verifier.records[0].claim.actual == actual
    verifier.records[0].validate_sources(verifier.observations)


def test_partial_bundle_retains_verified_blocker_without_claiming_complete_analysis(verification_case):
    provider,snapshot = verification_case()
    class PartialDiscovery:
        def run_result(self,bundle,tools):
            c = candidate()
            c.bundle_id = bundle.id
            return AgentRunResult(status="PARTIAL",candidates=[c],
                protocol_errors=[{"stage":"proof","error":"invalid sibling"}])
    result = ReviewRuntime(agent=PartialDiscovery(),rule_engine=lambda *a,**k:[]).run(SimpleNamespace(
        review_snapshot=snapshot,input_provider=provider,repo_dir=str(provider.root),
        pr_base_sha=snapshot.base_sha,pr_head_sha=snapshot.head_sha,
        files_changed=["app.py"],full_diff=provider.diff(snapshot)))
    assert result.health.status == "partial" and result.decision == "REQUEST_CHANGES"
    assert len(result.product_findings) == 1 and not result.approval_eligible
    assert result.inspection.inspected == 0
