"""
Stage 7/9 — code_quality_agent (core/agents.py)

Run: python manual_tests/07_test_code_quality_agent.py
Prerequisite: 03_test_evidence_retrieval.py (needs state["evidence_package"],
state["pr_understanding"], state["pr_analysis"]) against the real
NousResearch/hermes-agent PR #66302.

Compare this stage's findings against stage 6's (correctness_agent) for the
same PR — they should differentiate: correctness should flag things that will
actually break at runtime, quality should flag style/maintainability/tech-debt
concerns. If both agents restate the same finding with the same reasoning on
this real PR, that's a sign their prompts aren't differentiated enough yet.

By default this forces "code_quality_review" onto your local Ollama model.
Comment out force_local_models() to test the real routing (gpt-4o-mini by
default) — requires OPENAI_API_KEY.
"""

from ._common import load_state, save_state, print_stage, force_local_models

force_local_models()

from core.agents import code_quality_agent  # noqa: E402
from core.evidence import EvidencePackage  # noqa: E402

state = load_state()
if "evidence_package" not in state:
    raise SystemExit(
        "state.json has no 'evidence_package'. Run "
        "03_test_evidence_retrieval.py first."
    )

state["evidence_package"] = EvidencePackage(**state["evidence_package"])

print("Calling code_quality_agent...")
output = code_quality_agent(state)

print_stage("code_quality_agent", output)
save_state(output)
print("Saved merged state -> manual_tests/outputs/state.json")
