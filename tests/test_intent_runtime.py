"""Intent traverses the real runtime; scripted model outputs are not quality metrics."""
import json
from types import SimpleNamespace

import pytest

from core.agent.bundle_agent import BundleAgent
from core.intent.service import load_intent
from core.runtime.review_runtime import ReviewRuntime


BASE = "a" * 40
HEAD = "b" * 40
DIFF = (
    "diff --git a/app.py b/app.py\n--- a/app.py\n+++ b/app.py\n@@ -1,4 +1,2 @@\n"
    " def divide(value, denominator):\n-    if denominator == 0:\n-        return 0\n"
    "     return value / denominator\n"
)


@pytest.fixture
def intent(tmp_path):
    path = tmp_path / "requirements.json"
    path.write_text(json.dumps({"requirements": [{
        "id": "R1", "description": "Zero denominator contract",
        "acceptance_criterion": "divide(value, 0) returns zero rather than raising.", "paths": ["app.py"],
    }]}))
    return load_intent(path)


def run_review(intent, assessment="VIOLATED", diff=DIFF):
    prompts = []
    def discover(prompt):
        prompts.append(prompt)
        return "[]"
    runtime = ReviewRuntime(llm=discover, verification_llm=lambda prompt: assessment)
    result = runtime.run(SimpleNamespace(
        review_intent=intent, pr_head_sha=HEAD, pr_base_sha=BASE,
        files_changed=["app.py"], full_diff=diff, repo="", number=0,
    ))
    return result, prompts


def test_requirement_reaches_investigation_and_confirmed_defect(intent):
    result, prompts = run_review(intent)
    assert any(intent.items[0].acceptance_criterion in prompt for prompt in prompts)
    assert result.product_findings
    assert result.requirement_assessments[0].status == "violated"
    assert result.requirement_coverage.violated == 1
    assert result.investigations[0].status == "confirmed"
    assert result.evidence[0].revision_sha == HEAD
    assert result.product_findings[0].evidence_ids
    assert result.to_dict()["requirements"][0]["id"] == "R1"


@pytest.mark.parametrize("answer", ["UNVERIFIED", "Not VIOLATED", "VERIFIED", ""])
def test_unlinked_or_malformed_assessment_does_not_claim_violation(intent, answer):
    result, _ = run_review(intent, assessment=answer)
    assert result.requirement_assessments[0].status == "unverified"
    assert result.evidence == []
    assert any(item.get("requirement_id") == "R1" for item in result.unresolved)


def test_clean_change_does_not_establish_requirement_satisfaction(intent):
    diff = "diff --git a/app.py b/app.py\n--- a/app.py\n+++ b/app.py\n@@ -1 +1 @@\n-value = 1\n+value = 2\n"
    result, _ = run_review(intent, diff=diff)
    assert result.product_findings == []
    assert result.requirement_assessments[0].status == "unverified"
    assert not result.approval_eligible


def test_requirements_apply_only_to_explicit_paths(intent):
    assert intent.for_paths(["other.py"]) == []
    assert intent.for_paths(["app.py"])[0]["id"] == "R1"


def test_duplicate_requirements_are_rejected(tmp_path):
    path = tmp_path / "requirements.json"
    item = {"id": "R1", "description": "Rule", "acceptance_criterion": "Rule holds", "paths": ["app.py"]}
    path.write_text(json.dumps({"requirements": [item, item]}))
    with pytest.raises(ValueError, match="duplicate requirement"):
        load_intent(path)
