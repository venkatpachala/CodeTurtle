"""
Stage 4/9 — context_summarizer (core/agents.py)

Run: python manual_tests/04_test_context_summarizer.py
Prerequisite: 03_test_evidence_retrieval.py (needs state["context_from_kb"]),
which by default runs against the real NousResearch/hermes-agent PR #66302
using your already-indexed Qdrant collection.

By default this forces every AIGateway capability onto your local Ollama model
(force_local_models()) so you can iterate on prompts without an OPENAI_API_KEY.
Comment out that call below to test the real routing in
core/gateway/gateway.py's model_registry instead (this capability,
"summarization", already defaults to Ollama either way).
"""

from ._common import load_state, save_state, print_stage, force_local_models

force_local_models()  # remove this line to use the real (possibly cloud) routing

from core.agents import context_summarizer  # noqa: E402

state = load_state()
if "context_from_kb" not in state:
    raise SystemExit(
        "state.json has no 'context_from_kb'. Run "
        "03_test_evidence_retrieval.py first."
    )

print("Calling context_summarizer...")
output = context_summarizer(state)

print_stage("context_summarizer", output)
save_state(output)
print("Saved merged state -> manual_tests/outputs/state.json")
