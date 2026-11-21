"""Requirement-first investigation without pre-existing candidates or live providers."""
import json

import pytest

from core.input.snapshot import GitSnapshotProvider
from core.intent.investigator import RequirementInvestigator
from core.intent.service import load_intent
from core.review.budget import ReviewBudget
from tests.test_input_snapshot import git, repository

BEFORE = "def size(items):\n    if items is None:\n        return 0\n    return len(items)\n"
AFTER = "def size(items):\n    return len(items)\n"


@pytest.fixture
def requirement_case(repository):
    root, _ = repository
    (root / "app.py").write_text(BEFORE)
    git(root, "add", ".")
    git(root, "commit", "-m", "contract base")
    base = git(root, "rev-parse", "HEAD")
    (root / "app.py").write_text(AFTER)
    git(root, "add", ".")
    git(root, "commit", "-m", "contract head")
    path = root / "requirements.json"
    path.write_text(json.dumps({"requirements": [{"id": "R1", "description": "None input",
        "acceptance_criterion": "size(None) returns zero", "paths": ["app.py"]}]}))
    provider = GitSnapshotProvider(root)
    return provider, provider.resolve(base), load_intent(path)


def decision_for(prompt, outcome="violated"):
    package = json.loads(prompt.split("\nPACKAGE\n", 1)[1])
    observations = package["observations"]
    citations = [{"observation_id": obs["id"], "start_line": 1, "end_line": obs["end_line"], "quote": obs["text"]}
                 for obs in observations if obs["status"] == "success" and obs["text"]]
    return {"requirement_id": "R1", "outcome": outcome, "rationale": "HEAD passes None to len without a guard",
            "checked_scope": "Direct invocation of size(None)", "citations": citations,
            "counterevidence": [], "missing_evidence": [], "title": "None input raises TypeError",
            "trigger": "items is None", "expected": "0", "actual": "TypeError", "symbol": "size",
            "execution_path": ["size"], "severity": "medium",
            "anchor_observation_id": next(obs["id"] for obs in observations if obs["revision_side"] == "head"),
            "anchor_line": 2}


def test_planning_finds_a_candidate_without_any_discovery_findings(requirement_case):
    provider, snapshot, intent = requirement_case
    calls = []
    def complete(stage, prompt):
        calls.append(stage)
        return json.dumps(decision_for(prompt))
    runs = RequirementInvestigator(complete, ReviewBudget()).run(intent, provider, snapshot, ["app.py"])
    assert calls == ["investigate", "verify"]
    assert runs[0].status == "proposed_violation"
    assert runs[0].candidate.hypothesis_id == runs[0].id
    assert runs[0].candidate.file == "app.py"
    assert len(runs[0].observations) == 2


@pytest.mark.parametrize("kind", ["quote", "observation", "base_only", "missing_base"])
def test_unsupported_evidence_never_creates_a_candidate(requirement_case, kind):
    provider, snapshot, intent = requirement_case
    def complete(stage, prompt):
        decision = decision_for(prompt)
        if kind == "quote":
            decision["citations"][0]["quote"] = "invented source"
        elif kind == "observation":
            decision["citations"][0]["observation_id"] = "not retrieved"
        else:
            decision["citations"] = decision["citations"][:1] if kind == "base_only" else decision["citations"][1:]
        return json.dumps(decision)
    run = RequirementInvestigator(complete, ReviewBudget()).run(intent, provider, snapshot, ["app.py"])[0]
    assert run.status == "error"
    assert run.candidate is None


def test_fresh_verifier_disagreement_remains_unresolved(requirement_case):
    provider, snapshot, intent = requirement_case
    def complete(stage, prompt):
        return json.dumps(decision_for(prompt, "violated" if stage == "investigate" else "satisfied"))
    run = RequirementInvestigator(complete, ReviewBudget()).run(intent, provider, snapshot, ["app.py"])[0]
    assert run.status == "unresolved"
    assert "disagree" in run.reason
    assert run.candidate is None


@pytest.mark.parametrize("calls,expected", [(0, "not_assessed"), (1, "unresolved")])
def test_budget_before_or_during_assessment_is_explicit(requirement_case, calls, expected):
    provider, snapshot, intent = requirement_case
    runner = RequirementInvestigator(lambda stage, prompt: json.dumps(decision_for(prompt)),
                                     ReviewBudget(max_model_calls=calls))
    run = runner.run(intent, provider, snapshot, ["app.py"])[0]
    assert run.status == expected
    assert run.candidate is None


def test_disabled_and_admission_limits_do_not_claim_attempted_coverage(requirement_case):
    provider, snapshot, intent = requirement_case
    runner = RequirementInvestigator(lambda *_: pytest.fail("model should not run"), ReviewBudget(), max_requirements=0)
    run = runner.run(intent, provider, snapshot, ["app.py"])[0]
    assert run.status == "not_assessed" and not run.attempted
    assert run.observations == ()


def test_bare_verdict_cannot_establish_requirement_support(requirement_case):
    provider, snapshot, intent = requirement_case
    run = RequirementInvestigator(lambda *_: "VIOLATED", ReviewBudget()).run(intent, provider, snapshot, ["app.py"])[0]
    assert run.status == "error"


def test_declared_missing_external_context_cannot_be_conclusive(requirement_case):
    provider, snapshot, intent = requirement_case
    item = intent.items[0].model_copy(update={"context_paths": ("external_policy.py",)})
    intent = intent.model_copy(update={"items": (item,)})
    run = RequirementInvestigator(lambda stage, prompt: json.dumps(decision_for(prompt)), ReviewBudget()).run(
        intent, provider, snapshot, ["app.py"])[0]
    assert run.status == "error"
    assert "incomplete context" in run.reason


def test_one_protocol_repair_is_grounded_and_counts_against_shared_budget(requirement_case):
    provider, snapshot, intent = requirement_case
    calls = []
    def complete(stage, prompt):
        calls.append(stage)
        if len(calls) == 1:
            return "VIOLATED"
        if len(calls) == 2:
            package = json.loads(prompt.split("\nPACKAGE\n", 1)[1])
            assert "format_repair" in package
        return json.dumps(decision_for(prompt))
    budget = ReviewBudget()
    run = RequirementInvestigator(complete, budget).run(intent, provider, snapshot, ["app.py"])[0]
    assert run.status == "proposed_violation"
    assert calls == ["investigate", "investigate", "verify"]
    assert budget.calls == 3
    assert run.responses[1]["attempt"] == 2


def test_invalid_source_is_not_retried_without_bound(requirement_case):
    provider, snapshot, intent = requirement_case
    calls = []
    def complete(stage, prompt):
        calls.append(stage)
        decision = decision_for(prompt)
        decision["citations"][0]["quote"] = "invented source"
        return json.dumps(decision)
    run = RequirementInvestigator(complete, ReviewBudget()).run(intent, provider, snapshot, ["app.py"])[0]
    assert run.status == "error"
    assert run.candidate is None
    assert len(calls) == 2
