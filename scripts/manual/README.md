# CodeTurtle — manual per-agent test scripts

Drop this `manual_tests/` folder into the root of your CodeTurtle repo (next to
`core/`, `cli/`, `config.py`). Every script now defaults to a REAL, LIVE target:
**NousResearch/hermes-agent PR #66302**, fetched fresh from GitHub every run,
retrieved against your real Qdrant index. Nothing is mocked, pre-written, or
fabricated — what prints to your terminal is exactly what your local model and
your indexed repo actually produced.

Each script calls one real agent function, unmodified, straight from `core/`.

## What was fixed to make this runnable at all

Before writing these, I found the review pipeline couldn't complete a single
run — several files referenced an undefined `gateway` variable, both LLM
providers were missing functions the gateway called, and one capability
(`context_gathering`) wasn't registered, which crashed with a `KeyError`. I
patched these directly in `core/` (not worked around in the test scripts) so
the prompts you're tuning live in one place — the real source files:

- `core/pr_understanding.py`, `core/pr_analysis.py` — now use
  `llm.with_structured_output(Schema)` (they already had `llm` built, just
  never used it).
- `core/gateway/providers/ollama_provider.py` — added the missing `generate()`
  function, fixed `structured_generate()` to accept the `model` kwarg and stop
  referencing itself recursively.
- `core/gateway/providers/openai_provider.py` — added the missing `generate()`
  function for consistency.
- `core/gateway/gateway.py` — `GatewayResponse.content` was typed `str`, which
  silently mangled structured (Pydantic) responses; changed to `Any`. Also
  fixed `_get_provider()`'s fallback, which crashed with `KeyError` for any
  capability not explicitly listed in `model_registry` (this is what
  `context_gatherer` hits).
- `core/reranker.py` — the rerank prompt's `{top_k}` wasn't in an f-string, so
  the literal text `{top_k}` was being sent to the LLM instead of a number.
- `cli/commands/init.py` — missing `Panel` import.

None of this touches agent *prompts* — only what was structurally broken
underneath them. The prompts themselves are untouched and are exactly what
you'll be iterating on.

## Prerequisites

1. **Ollama running locally** with the model in your `.env` / `config.py`
   pulled (default `qwen2.5-coder:7b`), plus the embedding model:
   ```
   ollama serve
   ollama pull qwen2.5-coder:7b
   ollama pull nomic-embed-text
   ```
2. **Qdrant running locally**, with `NousResearch/hermes-agent` already indexed
   (you said this is already done):
   ```
   docker run -p 6333:6333 qdrant/qdrant
   codeturtle add-repo NousResearch/hermes-agent   # only if not already indexed
   ```
3. **A GitHub token in your `.env`** (`GITHUB_TOKEN=...`, `public_repo` scope
   is enough) — stages 1, 2, and 3 fetch the real PR from the GitHub API and
   will get rate-limited or rejected without it.
4. Python deps from `pyproject.toml` installed in your environment.

## Running

From the repo root, against the default target (NousResearch/hermes-agent #66302):

```bash
# one stage at a time (recommended while tuning a specific agent's prompt)
python manual_tests/01_test_pr_understanding.py
python manual_tests/02_test_pr_analysis.py
python manual_tests/03_test_evidence_retrieval.py
python manual_tests/04_test_context_summarizer.py
python manual_tests/05_test_context_gatherer.py
python manual_tests/06_test_correctness_agent.py
python manual_tests/07_test_code_quality_agent.py
python manual_tests/08_test_critic_agent.py
python manual_tests/09_test_final_recommender.py

# or the whole chain at once
python manual_tests/run_all.py
```

To test a different repo/PR, pass `--repo`/`--pr` to stages 1, 2, or 3 (the
only ones that fetch from GitHub — 4 through 9 just read `state.json`):

```bash
python manual_tests/01_test_pr_understanding.py --repo owner/repo --pr 42
python manual_tests/run_all.py --repo owner/repo --pr 42
```

Each script prints the full raw structured output of that one agent, and
merges it into `manual_tests/outputs/state.json` — the same accumulating
state object `core/graph.py` builds via LangGraph, just materialized to disk
so you can run one node, inspect it, edit that agent's prompt, and re-run
just that node without paying for the whole pipeline (or a fresh GitHub call)
again. Stages 2 and 3 will also do a live GitHub fetch themselves if run
standalone without a prior `state.json`.

## The live target

`_fixtures.py` defines `DEFAULT_REPO = "NousResearch/hermes-agent"` and
`DEFAULT_PR = 66302`, pulled live via `_live_pr.py` (identical fetch logic to
`cli/commands/review.py`'s `ReviewPipeline._fetch_pr`/`_build_full_diff`).
Since this is a real PR, not a fixture with known planted bugs, your ground
truth is the actual diff: open
https://github.com/NousResearch/hermes-agent/pull/66302/files side by side
with each stage's output and judge the findings against what's really there.

One real thing to watch for in stage 3, not a bug: `RepositoryIntelligence`'s
scanner only indexes `.py/.md/.txt/.rst/.yaml/.yml/.json/.toml`. If
hermes-agent is largely non-Python, expect a thin index and correspondingly
thin/irrelevant retrieval — that's the retriever accurately reporting a real
limitation of what got embedded, not a script problem.

`_fixtures.py` still has `SAMPLE_PR`, an offline fixture with 5 deliberately
planted bugs, kept as a fallback for testing without network access — it's no
longer used by default, but you can wire any script back to it if you want a
known-answer sanity check with zero GitHub/Qdrant dependency.

## Local vs. cloud models

By default, `AIGateway.model_registry` routes several capabilities
(`correctness_review`, `code_quality_review`, `final_recommendation`,
`security_review`, `performance_review`, `api_compatibility_review`) to
OpenAI, not Ollama — that's the real routing `core/graph.py` uses in
production. Scripts 04–09 call `force_local_models()` so you can iterate for
free without an `OPENAI_API_KEY`. Comment that call out in any script when
you want to test the actual model each capability is configured for.

## Known non-prompt issue worth knowing before you tune stage 8

`critic_agent` (stage 8) currently makes no LLM call — it just concatenates
`correctness_findings + quality_findings`. There's no prompt to tune there
yet; if you want it to actually critique (deduplicate, cross-check evidence,
drop low-confidence findings) that logic needs to be added first. The test
script for it will make this obvious — the "raw output" is just the two
input lists stitched together.
