"""Production proof contracts, bounded admission, and preserved live failure replay."""
import json

import pytest

from core.agent.bundle_agent import BundleAgent
from core.agent.hypothesis import ReviewHypothesis
from core.agent.proof import proof_schema, validate_batch, run_proofs, compact_evidence
from core.review.budget import ReviewBudget
from core.runtime.models import Bundle
from tests.test_proof_repair import FIXTURE


def hypothesis(number=1):
    return ReviewHypothesis(id=f"H-{number:03d}", bundle_id="B-001", file="app.py", symbol="size",
        category="correctness", observation="guard changed", hypothesis="None may reach len",
        required_evidence=["source"], confidence=0.6)


def response(prompt):
    package = json.loads(prompt.split("\nPACKAGE\n", 1)[1])
    return {"decisions": [{"hypothesis_id": item["id"], "status": "unresolved", "candidate": None,
        "reason": "External behavior remains unknown", "evidence_refs": [],
        "missing_evidence": ["external caller contract"]} for item in package["hypotheses"]]}


@pytest.mark.parametrize("kind", ["foreign_id", "duplicate", "missing", "foreign_evidence", "candidate_without_support"])
def test_invalid_proof_decisions_cannot_cross_contract_boundaries(kind):
    hyps = [hypothesis(), hypothesis(2)]
    decisions = [{"hypothesis_id": h.id, "status": "unresolved", "candidate": None,
                  "reason": "unknown", "evidence_refs": [], "missing_evidence": ["caller"]} for h in hyps]
    if kind == "foreign_id":
        decisions[0]["hypothesis_id"] = "OTHER"
    elif kind == "duplicate":
        decisions[1] = decisions[0]
    elif kind == "missing":
        decisions.pop()
    elif kind == "foreign_evidence":
        decisions[0]["evidence_refs"] = ["not-in-package"]
    else:
        decisions[0]["status"] = "substantiated"
    with pytest.raises(ValueError):
        validate_batch(json.dumps({"decisions": decisions}), proof_schema(hyps), hyps, [])


def test_five_hypotheses_fit_three_small_requests_within_four_total_steps():
    hyps = [hypothesis(n) for n in range(1, 6)]
    outputs = ["discovery already happened"]
    admitted = []
    def complete(prompt, schema):
        value = response(prompt)
        admitted.append(len(value["decisions"]))
        return json.dumps(value)
    result = run_proofs(Bundle(id="B-001", paths=["app.py"]), hyps, [], complete, outputs, max_steps=4)
    assert result.status == "VALID_EMPTY"
    assert admitted == [2, 2, 1]
    assert len(outputs) == 4 and len(result.outcomes) == 5
    assert not result.candidates


def test_actual_litellm_failure_gets_one_repair_and_keeps_deferred_work_visible():
    prompts = []
    def complete(prompt):
        prompts.append(prompt)
        if len(prompts) == 1:
            return FIXTURE["discovery"]
        if len(prompts) == 2:
            return FIXTURE["invalid_proof"]
        return json.dumps(response(prompt))
    agent = BundleAgent(llm=complete)
    agent.budget = ReviewBudget()
    result = agent.run_result(Bundle(id="B-001", paths=["litellm/batches/main.py", "tests/unit/batches/test_main.py"]))
    assert result.status == "PARTIAL"
    assert len(prompts) == agent.budget.calls == 4
    assert len(result.hypotheses) == len(result.hypothesis_outcomes) == 5
    assert result.proof_runs[0]["status"] == "completed"
    assert result.proof_runs[-1]["status"] == "not_assessed"
    assert result.protocol_errors and not result.candidates
    assert "protocol_repair" in prompts[2]


def test_provider_truncation_is_not_accepted_even_when_raw_json_parses():
    calls = []
    def complete(prompt, schema):
        calls.append(prompt)
        return json.dumps(response(prompt))
    result = run_proofs(Bundle(id="B1"), [hypothesis()], [], complete, ["discovery"], max_steps=4,
                        metadata=lambda: {"output_truncated": True, "finish_reason": "length"})
    assert len(calls) == 2 and not result.candidates
    assert result.status == "INVALID_SCHEMA"
    assert result.records[0]["attempts"][0]["finish_reason"] == "length"


def test_only_one_repair_is_available_for_the_whole_bundle():
    calls = []
    def complete(prompt, schema):
        calls.append(prompt)
        return "invalid"
    result = run_proofs(Bundle(id="B1"), [hypothesis(n) for n in range(1, 6)], [], complete,
                        ["discovery"], max_steps=10)
    assert len(calls) == 4  # 3 batches + one repair, not one repair per batch.
    assert all(item["status"] == "unresolved" for item in result.outcomes)


def test_prompt_compaction_marks_clipping_and_omitted_evidence():
    evidence = [{"id": f"E{n}", "request": {"path": "app.py"}, "result": {"text": "x" * 5000}} for n in range(3)]
    selected, omitted = compact_evidence(evidence, [hypothesis()], max_chars=3000)
    assert len(selected) == 1 and len(omitted) == 2
    assert selected[0]["result"]["truncated"]
    assert evidence[0]["result"]["text"] == "x" * 5000  # Original observation remains intact.


def test_supported_candidate_retains_scoped_identity_and_proof_fields():
    candidate = {"file": "app.py", "symbol": "size", "start_line": 2,
        "title": "None input raises", "claim": "None reaches len", "existing_code": "return len(items)",
        "invariant": "None returns zero", "violating_condition": "items is None", "expected": "0",
        "actual": "TypeError", "execution_path": ["size"], "severity": "medium", "confidence": 0.8}
    payload = {"decisions": [{"hypothesis_id": "H-001", "status": "substantiated", "candidate": candidate,
        "reason": "HEAD removed the guard", "evidence_refs": ["E1"], "missing_evidence": []}]}
    evidence = [{"id": "E1", "request": {"path": "app.py"}, "result": {"text": "return len(items)"}}]
    result = run_proofs(Bundle(id="B-001", paths=["app.py"]), [hypothesis()], evidence,
                        lambda prompt, schema: json.dumps(payload), ["discovery"], max_steps=4)
    assert result.status == "VALID_CANDIDATES"
    assert result.candidates[0].hypothesis_id == "H-001"
    assert result.candidates[0].bundle_id == "B-001"
    assert result.candidates[0].verify_status == "candidate"  # Final verification is still mandatory.
    assert result.candidates[0].source == "agent"


def test_failed_provider_attempt_still_consumes_a_step_and_is_recorded():
    calls = []
    def complete(prompt, schema):
        calls.append(prompt)
        if len(calls) == 1:
            return "invalid"
        if len(calls) == 2:
            raise RuntimeError("provider failed before returning content")
        return json.dumps(response(prompt))
    result = run_proofs(Bundle(id="B1"), [hypothesis(n) for n in range(1, 6)], [], complete,
                        ["discovery"], max_steps=4)
    assert len(calls) == 3  # Four steps include discovery and the failed repair request.
    assert result.records[0]["status"] == "provider_error"
    assert len(result.records[0]["attempts"]) == 2
    assert result.records[0]["attempts"][1]["response_index"] is None
    assert result.records[-1]["status"] == "not_assessed"
    assert result.status == "PARTIAL"
