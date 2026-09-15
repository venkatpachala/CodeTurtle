"""
Stage 9/9 — final_recommender (core/agents.py)

Run: python manual_tests/09_test_final_recommender.py
Prerequisite: 08_test_critic_agent.py (needs state["findings"], state["context_summary"]),
run against the real NousResearch/hermes-agent PR #66302.

This is the last stage — it decides MERGE / REQUEST_CHANGES / COMMENT. Since
PR #66302 is a real, presumably already-reviewed/merged fix, worth checking:
does the recommendation and confidence line up with what you'd expect for a
narrowly-scoped runtime bugfix PR? If it comes back REQUEST_CHANGES with low
specificity, or MERGE despite high-severity findings from stage 6/7, that's a
sign the prompt in final_recommender() (core/agents.py) needs stronger
guardrails tying the recommendation directly to finding severity rather than
trusting the LLM to weigh it correctly on its own.

By default this forces "final_recommendation" onto your local Ollama model.
Comment out force_local_models() to test the real routing (gpt-4o-mini by
default) — requires OPENAI_API_KEY.
"""

from ._common import load_state, save_state, print_stage, force_local_models

force_local_models()

from core.agents import final_recommender  # noqa: E402
from core.models import Finding  # noqa: E402

state = load_state()
if "findings" not in state or "context_summary" not in state:
    raise SystemExit(
        "state.json is missing findings/context_summary. Run "
        "08_test_critic_agent.py first."
    )

state["findings"] = [Finding(**f) if isinstance(f, dict) else f for f in state["findings"]]

print("Calling final_recommender...")
output = final_recommender(state)

print_stage("final_recommender", output)
save_state(output)
print("Saved merged state -> manual_tests/outputs/state.json")

print(f"\nFINAL RECOMMENDATION: {output['recommendation']}")
print(f"SUMMARY: {output['final_comment']}")
