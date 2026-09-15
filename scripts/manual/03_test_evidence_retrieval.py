"""
Stage 3/9 — build_evidence_package (core/agents.py), backed by HybridRetriever
(core/hybrid_retriever.py) + your real Qdrant index + the LLM reranker
(core/reranker.py).

Run: python manual_tests/03_test_evidence_retrieval.py [--repo owner/repo --pr 123]

You said you've already run `codeturtle add-repo NousResearch/hermes-agent`, so
this hits your real Qdrant collection "NousResearch_hermes-agent" and your real
Ollama embedding model (nomic-embed-text), plus one real LLM call for reranking.
Nothing here is mocked. If Qdrant has nothing relevant indexed you'll get back a
thin/empty EvidencePackage — that's real signal about your index, not a bug in
this script.

This is the stage to focus on if findings later on feel generic/ungrounded —
if the retrieved evidence isn't relevant, no amount of prompt tuning on the
correctness/quality agents downstream will fix that.
"""

import argparse

from ._common import load_state, save_state, print_stage, OUTPUTS_DIR
from ._fixtures import DEFAULT_REPO, DEFAULT_PR
from ._live_pr import fetch_live_pr

parser = argparse.ArgumentParser()
parser.add_argument("--repo", default=DEFAULT_REPO, help="owner/repo exactly as passed to `codeturtle add-repo`")
parser.add_argument("--pr", type=int, default=DEFAULT_PR)
args = parser.parse_args()

from core.agents import build_evidence_package  # noqa: E402
from core.evidence import EvidencePackage  # noqa: E402

state = load_state()
if "full_diff" not in state:
    print("No prior state.json with PR data found — fetching the PR live.")
    state = {**state, **fetch_live_pr(args.repo, args.pr)}
state["repo"] = args.repo  # always honor the --repo flag over whatever was saved

print(f"\nRunning build_evidence_package against your real Qdrant collection "
      f"'{args.repo.replace('/', '_')}' ...\n")
output = build_evidence_package(state)
evidence_pkg: EvidencePackage = output["evidence_package"]

print("=" * 78)
print(f"  RETRIEVAL QUERY (title + body, truncated): {evidence_pkg.query[:150]!r}")
print("=" * 78)

if not evidence_pkg.evidences:
    print("\n*** Retrieved 0 evidence chunks. ***")
    print("This usually means one of:")
    print(f"  - The '{args.repo.replace('/', '_')}' Qdrant collection is empty or")
    print(f"    doesn't exist (re-check with `codeturtle inspect-kb {args.repo}`).")
    print(f"  - The repo is mostly non-Python: core/repository_intelligence.py's")
    print(f"    scanner only indexes .py/.md/.txt/.rst/.yaml/.yml/.json/.toml —")
    print(f"    if hermes-agent is e.g. mostly TS/Go, most of it was never embedded.")
else:
    for i, ev in enumerate(evidence_pkg.evidences, 1):
        print(f"\n--- Evidence #{i} ---")
        print(f"path           : {ev.path}")
        print(f"lines          : {ev.start_line}-{ev.end_line}")
        print(f"chunk_type     : {ev.chunk_type}")
        print(f"symbols        : {ev.symbols}")
        print(f"retrieval_type : {ev.retrieval_type}   (vector = Qdrant similarity, symbol = substring match)")
        print(f"score          : {ev.score}")
        print(f"reason         : {ev.reason}")
        print(f"content (first 500 chars):\n{ev.content[:500]}")

print(f"\n{'=' * 78}\n  evidence_package.summary\n{'=' * 78}")
print(evidence_pkg.summary)

print(f"\n{'=' * 78}\n  context_from_kb — exact text handed to every downstream agent\n{'=' * 78}")
print(output["context_from_kb"])

print(f"\naffected_files : {evidence_pkg.affected_files}")
print(f"related_symbols: {evidence_pkg.related_symbols}")
print(f"\nTotal evidence chunks retrieved: {len(evidence_pkg.evidences)}")

save_state({**state, **output})
print(f"\nSaved merged state -> {OUTPUTS_DIR}/state.json")
