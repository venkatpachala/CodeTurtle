# Ship validation — v0.2.0

Date: 2026-09-15
Repo/PR: confident-ai/deepeval#3288
Classification: source
Change units n=: 2
Investigate: run
Decision: REQUEST_CHANGES
Graphify stats: nodes=19152 edges=57321 communities=0
Command used: `codeturtle review confident-ai/deepeval 3288 --dry-run -v`

## Result

- Process exit: 0
- `[PRFacts] files=2 classification=source lock=0 source=2`
- `[ChangeUnits] n=2 source=1 test=1`
- Retrieval: Graphify only (Qdrant disabled). No Qdrant “storage folder already accessed” crash.
- `--dry-run mode (not posted)` — `create_review` was not called.
- Final decision: `REQUEST_CHANGES` (policy_reason=supported_medium)
- Title: `fix(kimi): keep unknown pricing as None instead of raising`
- Files: `deepeval/models/llms/kimi_model.py`, `tests/test_core/test_models/test_kimi_model.py`

## Commands

```bash
codeturtle new-session
graphify extract . --code-only --no-cluster   # in repos/confident-ai_deepeval
codeturtle graphify-test confident-ai/deepeval --stats -v
codeturtle review confident-ai/deepeval 3288 --dry-run -v
uv run python -m tests.evaluation.run_eval --offline
```

## Regression

Offline goldens `qw-538` and `qw-571` still PASS. Added `deepeval-3288` from this live dry-run snapshot (not mocked).

## GitHub Release body (draft — human pushes)

```text
Install: uv tool install git+https://github.com/venkatpachala/CodeTurtle.git@v0.2.0
Smoke: confident-ai/deepeval#3288 --dry-run → REQUEST_CHANGES
Requires: GitHub token, local or cloud LLM, Graphify for structure.
Default is dry-run.
```
