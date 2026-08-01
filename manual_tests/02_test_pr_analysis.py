"""
Stage 2/9 — pr_analysis_agent (core/pr_analysis.py)

Run: python manual_tests/02_test_pr_analysis.py [--repo owner/repo --pr 123]
Prerequisite: run 01_test_pr_understanding.py first (recommended). If you run
this standalone with no prior state.json, it fetches the PR live itself using
the same --repo/--pr defaults.

Note: this agent's docstring says "Deterministic + LLM" but the deterministic
half (parsing the diff/AST directly instead of asking the LLM to guess
insertions/deletions/modified_functions) is currently a TODO in the source —
it's 100% LLM-guessed today. Worth checking whether the numbers it returns
(insertions/deletions especially) are close to the real PR's actual diff stats
(this script prints the real file count from GitHub in stage 1's output for
comparison); if they're consistently off, that's an argument for implementing
the deterministic diff-parsing part instead of tuning the prompt further.
"""

import argparse

from ._common import load_state, save_state, print_stage
from ._fixtures import DEFAULT_REPO, DEFAULT_PR
from ._live_pr import fetch_live_pr

parser = argparse.ArgumentParser()
parser.add_argument("--repo", default=DEFAULT_REPO)
parser.add_argument("--pr", type=int, default=DEFAULT_PR)
args = parser.parse_args()

from core.pr_analysis import pr_analysis_agent  # noqa: E402

state = load_state()
if "full_diff" not in state:
    print("No prior state.json with PR data found — fetching the PR live.")
    state = {**state, **fetch_live_pr(args.repo, args.pr)}

print("\nCalling pr_analysis_agent against your local Ollama model...")
output = pr_analysis_agent(state)

print_stage("pr_analysis_agent", output)
save_state(output)
print("Saved merged state -> manual_tests/outputs/state.json")
