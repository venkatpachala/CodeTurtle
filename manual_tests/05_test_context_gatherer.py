"""
Stage 5/9 — context_gatherer (core/agents.py)

Run: python manual_tests/05_test_context_gatherer.py
Prerequisite: 04_test_context_summarizer.py (needs state["summarized_context"]),
built from the real PR fetched in stage 1/3.

Heads up while you tune this: context_summarizer (stage 4) and context_gatherer
(stage 5) currently do very similar things back-to-back — summarize the raw
retrieved context, then "gather" from that summary into yet another summary.
Compare this script's output to stage 4's output side by side; if they read as
redundant, that's worth fixing at the prompt/graph level (e.g. have this stage
extract something structurally different — like a checklist of things the final
recommender should weigh — rather than summarizing again).
"""

from ._common import load_state, save_state, print_stage, force_local_models

force_local_models()

from core.agents import context_gatherer  # noqa: E402

state = load_state()
if "summarized_context" not in state:
    raise SystemExit(
        "state.json has no 'summarized_context'. Run "
        "04_test_context_summarizer.py first."
    )

print("Calling context_gatherer...")
output = context_gatherer(state)

print_stage("context_gatherer", output)
save_state(output)
print("Saved merged state -> manual_tests/outputs/state.json")
