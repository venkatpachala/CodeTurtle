"""
Stage 6/9 — correctness_agent (core/agents.py)

Run: python manual_tests/06_test_correctness_agent.py
Prerequisite: 03_test_evidence_retrieval.py (needs state["evidence_package"],
state["pr_understanding"], state["pr_analysis"]) against the real
NousResearch/hermes-agent PR #66302.

This is the agent that's supposed to catch real functional bugs. Since this is
a real merged/open PR (not a fixture with known planted bugs), your scorecard
here is: open https://github.com/NousResearch/hermes-agent/pull/66302 side by
side, read the actual diff yourself, and judge whether this agent's findings
are (a) grounded in code that's actually in the diff, (b) not hallucinated
against files that weren't touched, and (c) proportionate — a title like
"fix(runtime): recover stale model and cache state" implies a narrow, specific
bug fix, so findings that read like a generic checklist are a sign the prompt
needs to push harder for diff-specific reasoning over the retrieved evidence.

By default this forces the "correctness_review" capability onto your local
Ollama model. Comment out force_local_models() to test the real routing
(gpt-4o by default in model_registry) — requires OPENAI_API_KEY.
"""

from ._common import load_state, save_state, print_stage, force_local_models

force_local_models()  # remove to test against the real (cloud) model for this capability

from core.agents import correctness_agent  # noqa: E402
from core.evidence import EvidencePackage  # noqa: E402

state = load_state()
if "evidence_package" not in state:
    raise SystemExit(
        "state.json has no 'evidence_package'. Run "
        "03_test_evidence_retrieval.py first."
    )

# evidence_package comes back from state.json as a plain dict (JSON round-trip) —
# rehydrate it into the real EvidencePackage object the agent expects.
state["evidence_package"] = EvidencePackage(**state["evidence_package"])

print("Calling correctness_agent...")
output = correctness_agent(state)

print_stage("correctness_agent", output)
print("Compare against the real diff: "
      "https://github.com/NousResearch/hermes-agent/pull/66302/files")
save_state(output)
print("Saved merged state -> manual_tests/outputs/state.json")
