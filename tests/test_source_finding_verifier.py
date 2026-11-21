"""Ground both acceptance and rejection using actual sealed Git observations."""
import json
import hashlib
from dataclasses import fields
from pathlib import Path

import pytest

from core.input.snapshot import GitSnapshotProvider
from core.runtime.models import Candidate
from core.review.budget import ReviewBudget
from core.verification.source_verifier import SourceFindingVerifier
from tests.test_input_snapshot import git, repository

PROTECTED = "def size(items):\n    if items is None:\n        return 0\n    return len(items)\n"
BROKEN = "def size(items):\n    return len(items)\n"


@pytest.fixture
def verification_case(repository):
    root, _ = repository
    def make(after=BROKEN, before=PROTECTED):
        (root / "app.py").write_text(before)
        git(root, "add", ".")
        git(root, "commit", "--allow-empty", "-m", "before")
        base = git(root, "rev-parse", "HEAD")
        (root / "app.py").write_text(after)
        git(root, "add", ".")
        git(root, "commit", "--allow-empty", "-m", "after")
        provider = GitSnapshotProvider(root)
        return provider, provider.resolve(base)
    return make


def candidate():
    return Candidate(bundle_id="B1", file="app.py", symbol="size", start_line=2, candidate_id="C-001",
        title="None input raises TypeError", claim="size(None) raises TypeError after the guard is removed",
        invariant="size(None) returns zero", violating_condition="items is None",
        expected="0", actual="TypeError", existing_code="return len(items)", execution_path=["size"],
        evidence=["app.py"], evidence_paths=["app.py"], confidence=0.9)


def response_for(prompt, verdict="supported", side="head", basis="none"):
    package = json.loads(prompt.split("\nPACKAGE\n", 1)[1])
    observations = package[f"{side}_observations"]
    obs = observations[0]
    lines = obs["text"].splitlines()
    citation = {"observation_id": obs["id"], "start_line": 1, "end_line": len(lines), "quote": obs["text"]}
    return {"verdict": verdict, "checked_trigger": package["candidate"]["violating_condition"],
            "rationale": "The supplied HEAD operation and trigger determine this outcome",
            "path_analysis": "Direct size(None) invocation reaches len or the preceding return",
            "supporting_citations": [citation] if verdict == "supported" else [],
            "counter_citations": [citation] if verdict == "refuted" else [],
            "missing_evidence": [], "refutation_basis": basis}


def test_removed_guard_is_supported_with_head_evidence_and_recorded_trace(verification_case):
    provider, snapshot = verification_case()
    budget = ReviewBudget()
    verifier = SourceFindingVerifier(provider, snapshot, lambda prompt: json.dumps(response_for(prompt)), budget)
    assert verifier.verify(candidate(), None, []) == "VERIFIED"
    assert verifier.records[0].verdict == "supported"
    assert verifier.records[0].decision.supporting_citations
    assert budget.calls == 1


@pytest.mark.parametrize("kind", ["bare", "base_guard", "invented", "missing", "wrong_trigger"])
def test_unsupported_verdicts_never_promote_or_refute(verification_case, kind):
    provider, snapshot = verification_case()
    def complete(prompt):
        if kind == "bare":
            return "VERIFIED"
        decision = response_for(prompt, "refuted" if kind == "base_guard" else "supported",
                                "base" if kind == "base_guard" else "head", "head_guard" if kind == "base_guard" else "none")
        if kind == "invented":
            decision["supporting_citations"][0]["quote"] = "invented source"
        elif kind == "missing":
            decision["missing_evidence"] = ["external policy unavailable"]
        elif kind == "wrong_trigger":
            decision["checked_trigger"] = "other is None"
        return json.dumps(decision)
    verifier = SourceFindingVerifier(provider, snapshot, complete, ReviewBudget())
    assert verifier.verify(candidate(), None, []) == "UNCERTAIN"
    assert verifier.records[0].status == "invalid_response"
    assert len(verifier.records[0].attempts) == 2


def test_active_head_guard_can_refute_specific_trigger(verification_case):
    provider, snapshot = verification_case(after=PROTECTED)
    verifier = SourceFindingVerifier(provider, snapshot,
        lambda prompt: json.dumps(response_for(prompt, "refuted", basis="head_guard")), ReviewBudget())
    assert verifier.verify(candidate(), None, []) == "DISPROVED"
    assert verifier.records[0].decision.counter_citations


@pytest.mark.parametrize("after", [
    "def size(items, other=None):\n    if other is None:\n        return 0\n    return len(items)\n",
    "def size(items, flag=False):\n    if flag:\n        if items is None:\n            return 0\n    return len(items)\n",
    BROKEN + "\ndef unrelated(other):\n    if other is None:\n        return 0\n",
])
def test_wrong_variable_conditional_or_unrelated_guard_is_not_proven_refutation(verification_case, after):
    provider, snapshot = verification_case(after=after)
    verifier = SourceFindingVerifier(provider, snapshot,
        lambda prompt: json.dumps(response_for(prompt, "refuted", basis="head_guard")), ReviewBudget())
    assert verifier.verify(candidate(), None, []) == "UNCERTAIN"


def test_cannot_support_a_trigger_blocked_by_a_direct_head_guard(verification_case):
    provider, snapshot = verification_case(after=PROTECTED)
    verifier = SourceFindingVerifier(provider, snapshot, lambda prompt: json.dumps(response_for(prompt)), ReviewBudget())
    assert verifier.verify(candidate(), None, []) == "UNCERTAIN"


def test_budget_provider_failure_and_missing_context_remain_distinct(verification_case):
    provider, snapshot = verification_case()
    exhausted = SourceFindingVerifier(provider, snapshot, lambda _: pytest.fail("no request"), ReviewBudget(max_model_calls=0))
    assert exhausted.verify(candidate(), None, []) == "UNCERTAIN"
    assert exhausted.records[0].status == "budget_exhausted"
    def fail(_):
        raise TimeoutError()
    failed = SourceFindingVerifier(provider, snapshot, fail, ReviewBudget())
    failed.verify(candidate(), None, [])
    assert failed.records[0].status == "provider_error"
    absent = SourceFindingVerifier(None, None, lambda _: pytest.fail("no source"), ReviewBudget())
    absent.verify(candidate(), None, [])
    assert absent.records[0].status == "context_unavailable"


def test_one_protocol_repair_is_validated_again_and_budgeted(verification_case):
    provider, snapshot = verification_case()
    calls = []
    def complete(prompt):
        calls.append(prompt)
        return "VERIFIED" if len(calls) == 1 else json.dumps(response_for(prompt))
    budget = ReviewBudget()
    verifier = SourceFindingVerifier(provider, snapshot, complete, budget)
    assert verifier.verify(candidate(), None, []) == "VERIFIED"
    assert "protocol_repair" in calls[1]
    assert budget.calls == 2


def test_removed_base_guard_cannot_be_relabelled_as_preexisting_failure(verification_case):
    provider, snapshot = verification_case()
    def complete(prompt):
        decision = response_for(prompt, "refuted", basis="preexisting_failure")
        baseline = response_for(prompt, "supported", side="base")
        decision["supporting_citations"] = baseline["supporting_citations"]
        return json.dumps(decision)
    verifier = SourceFindingVerifier(provider, snapshot, complete, ReviewBudget())
    assert verifier.verify(candidate(), None, []) == "UNCERTAIN"
    assert "preexisting None failure" in verifier.records[0].reason


def test_preserved_live_false_negative_replays_through_grounded_gate(verification_case):
    """Reuse the exact stored candidate; scripted reasoning is a mechanism test."""
    directory = Path(__file__).resolve().parents[1] / "docs/validation/requirement-first-v3"
    payload = (directory / "predictions.json").read_bytes()
    seal = json.loads((directory / "seal.json").read_text())
    assert hashlib.sha256(payload).hexdigest() == seal["predictions_sha256"]
    previous = next(item for item in json.loads(payload) if item["case_id"] == "none-guard-removed"
                    and item["strategy"] == "investigate")["result"]
    rejected = next(item for item in previous["dropped"] if item["drop_reason"] == "disproved")
    claim = Candidate(**{item.name: rejected[item.name] for item in fields(Candidate) if item.name in rejected})
    source = {obs["revision_side"]: obs["text"] for obs in previous["source_observations"] if obs["path"] == claim.file}
    provider, snapshot = verification_case(after=source["head"] + "\n", before=source["base"] + "\n")
    verifier = SourceFindingVerifier(provider, snapshot, lambda prompt: json.dumps(response_for(prompt)), ReviewBudget())
    assert verifier.verify(claim, None, []) == "VERIFIED"
    assert verifier.records[0].claim.violating_condition == "size(None)"
    assert verifier.records[0].decision.supporting_citations
