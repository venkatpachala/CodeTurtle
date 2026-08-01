"""
Stage 8/9 — critic_agent (core/agents.py)

Run: python manual_tests/08_test_critic_agent.py
Prerequisite: 06_test_correctness_agent.py and 07_test_code_quality_agent.py,
run against the real NousResearch/hermes-agent PR #66302.

IMPORTANT while you're tuning prompts: as currently written, critic_agent
makes NO LLM call. It just concatenates correctness_findings + quality_findings
verbatim — no deduplication, no cross-checking one agent's claim against the
other's, no dropping of low-confidence noise. If you want the "skeptical
senior engineer" behavior the name implies, that logic needs to be added here
(an LLM pass over all findings + the diff, instructed to drop anything it
can't back up with the evidence, merge near-duplicates, and adjust confidence).
Run this script first to see the raw concatenation, then decide if/how to
turn it into a real reviewing step.
"""

from ._common import load_state, save_state, print_stage
from ._fixtures import SAMPLE_PR
from core.models import Finding

from core.agents import critic_agent  # noqa: E402

state = load_state()
if "correctness_findings" not in state or "quality_findings" not in state:
    raise SystemExit(
        "state.json is missing correctness_findings/quality_findings. Run "
        "06_test_correctness_agent.py and 07_test_code_quality_agent.py first."
    )

# Findings come back from state.json as plain dicts (JSON round-trip) — rehydrate
# them into real Finding objects since final_recommender (stage 9) will access
# .title / .severity / .description as attributes, not dict keys.
state["correctness_findings"] = [Finding(**f) for f in state["correctness_findings"]]
state["quality_findings"] = [Finding(**f) for f in state["quality_findings"]]

print("Calling critic_agent (note: currently a pure aggregator, no LLM call)...")
output = critic_agent(state)

print_stage("critic_agent", {**output, "findings": [f.model_dump() if isinstance(f, Finding) else f for f in output["findings"]]})
save_state(output)
print("Saved merged state -> manual_tests/outputs/state.json")
