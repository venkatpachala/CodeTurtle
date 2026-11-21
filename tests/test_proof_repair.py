"""Replay the observed LiteLLM failure without calling a model."""
import json
from pathlib import Path

import pytest

from core.agent.bundle_agent import BundleAgent
from core.agent.parse import parse_proof_output
from core.runtime.models import Bundle
from core.review.budget import ReviewBudget

FIXTURE = json.loads((Path(__file__).parent / "fixtures/proof-failures/litellm-53337.json").read_text(encoding="utf-8"))


def run(responses, *, steps=4, budget=12):
    prompts = []
    source = iter(responses)
    def complete(prompt):
        prompts.append(prompt)
        return next(source)
    agent = BundleAgent(llm=complete, max_steps=steps)
    agent.budget = ReviewBudget(max_model_calls=budget)
    bundle = Bundle(id="B-001", paths=["litellm/batches/main.py", "tests/unit/batches/test_main.py"])
    return agent.run_result(bundle), prompts, agent.budget


def test_preserved_response_is_truncated_and_not_salvaged():
    assert FIXTURE["reported_completion_tokens"] == 1400
    with pytest.raises(ValueError):
        parse_proof_output(FIXTURE["invalid_proof"])


@pytest.mark.parametrize("bad", [FIXTURE["invalid_proof"], '{"hypotheses": []}', '{"tool":"read_hunk"}', '{"evidence": []}'])
def test_invalid_proof_gets_one_budgeted_repair_with_preserved_evidence(bad):
    result, prompts, budget = run([FIXTURE["discovery"], bad, '{"candidates":[],"outcomes":[]}'])
    assert result.status == "VALID_EMPTY"
    assert result.hypotheses and not result.candidates
    assert len(prompts) == budget.calls == 3
    assert "Validation feedback:" in prompts[-1]
    assert "Investigation package:" in prompts[-1]
    assert len(result.protocol_errors) == 1


def test_repeated_invalid_output_never_becomes_a_clean_result():
    result, prompts, _ = run([FIXTURE["discovery"], FIXTURE["invalid_proof"], FIXTURE["invalid_proof"]])
    assert result.status == "INVALID_JSON"
    assert len(prompts) == 3 and len(result.protocol_errors) == 2
    assert not result.candidates and result.hypotheses


def test_step_limit_does_not_hide_an_extra_repair_call():
    result, prompts, _ = run([FIXTURE["discovery"], FIXTURE["invalid_proof"]], steps=2)
    assert result.status == "INVALID_JSON"
    assert len(prompts) == 2


def test_budget_exhaustion_preserves_hypotheses_and_invalid_attempt():
    result, prompts, budget = run([FIXTURE["discovery"], FIXTURE["invalid_proof"]], budget=2)
    assert result.status == "BUDGET_EXHAUSTED"
    assert result.hypotheses and result.protocol_errors
    assert len(prompts) == budget.calls == 2
