"""
Stage 1/9 — pr_understanding_agent (core/pr_understanding.py)

Run (defaults to your already-indexed repo/PR):
    python manual_tests/01_test_pr_understanding.py
    python manual_tests/01_test_pr_understanding.py --repo owner/repo --pr 123

Fetches the REAL PR from GitHub (title, body, files, diff) and calls the REAL
agent function unmodified from core/pr_understanding.py — this hits your local
Ollama server exactly the way core/graph.py would. Nothing here is mocked or
pre-written. Output is written into manual_tests/outputs/state.json so
02_test_pr_analysis.py etc. can build on it, just like the real LangGraph state.

To iterate on the prompt: edit the system/human prompt text directly inside
core/pr_understanding.py, then re-run this script. That's the actual prompt the
graph uses — editing it here is editing the source of truth.
"""

import argparse

from ._common import reset_state, save_state, print_stage
from ._fixtures import DEFAULT_REPO, DEFAULT_PR
from ._live_pr import fetch_live_pr

parser = argparse.ArgumentParser()
parser.add_argument("--repo", default=DEFAULT_REPO, help="owner/repo, already indexed via `codeturtle add-repo`")
parser.add_argument("--pr", type=int, default=DEFAULT_PR)
args = parser.parse_args()

reset_state()

from core.pr_understanding import pr_understanding_agent  # noqa: E402

initial_state = fetch_live_pr(args.repo, args.pr)

print("\nCalling pr_understanding_agent against your local Ollama model...")
output = pr_understanding_agent(initial_state)

print_stage("pr_understanding_agent", output)
save_state({**initial_state, **output})
print("Saved merged state -> manual_tests/outputs/state.json")
