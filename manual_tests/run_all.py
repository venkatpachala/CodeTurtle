"""
Runs all 9 stage scripts in sequence against a real PR (defaults to
NousResearch/hermes-agent #66302), exactly the order core/graph.py uses
(context_gatherer / correctness_agent / code_quality_agent run sequentially
here instead of in parallel, but that doesn't change their output — they
don't depend on each other, only on context_summarizer's output).

Run: python manual_tests/run_all.py [--repo owner/repo --pr 123]

Use this once each individual stage is behaving the way you want, to confirm
the whole chain still works end to end on a real PR. While actively tuning
ONE agent's prompt, prefer running that single numbered script instead —
faster feedback loop, and only 1 or 3 make GitHub API calls.
"""

import argparse
import subprocess
import sys
import os

THIS_DIR = os.path.dirname(os.path.abspath(__file__))

parser = argparse.ArgumentParser()
parser.add_argument("--repo", default="NousResearch/hermes-agent",
                     help="owner/repo, already indexed via `codeturtle add-repo`")
parser.add_argument("--pr", type=int, default=66302)
args = parser.parse_args()

pr_args = ["--repo", args.repo, "--pr", str(args.pr)]

STAGES = [
    ("01_test_pr_understanding.py", pr_args),
    ("02_test_pr_analysis.py", pr_args),
    ("03_test_evidence_retrieval.py", pr_args),
    ("04_test_context_summarizer.py", []),
    ("05_test_context_gatherer.py", []),
    ("06_test_correctness_agent.py", []),
    ("07_test_code_quality_agent.py", []),
    ("08_test_critic_agent.py", []),
    ("09_test_final_recommender.py", []),
]

for stage, extra_args in STAGES:
    print(f"\n\n########## RUNNING {stage} ##########")
    # Each stage runs as its own process (not in-process via runpy/import) so
    # that core.agents's module-level `gateway = AIGateway()` singleton is
    # rebuilt fresh every time — force_local_models() patches AIGateway.__init__
    # BEFORE that singleton is constructed only if this is a new process.
    result = subprocess.run(
        [sys.executable, os.path.join(THIS_DIR, stage), *extra_args],
        cwd=THIS_DIR,
    )
    if result.returncode != 0:
        print(f"\n{stage} failed (exit code {result.returncode}) — stopping.")
        sys.exit(result.returncode)
