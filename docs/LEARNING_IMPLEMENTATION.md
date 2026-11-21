# CodeTurtle implementation and learning guide

This project is an AI backend engineering portfolio project. Its claims must be
supported by reproducible code, tests, adjudicated evaluation, and recorded limits.
Commit count is not a quality metric. Each commit should explain one coherent change.

## Working cycle

For each slice:

1. Identify a concrete failure or missing capability.
2. State the contract and its failure behavior.
3. Make the smallest integrated implementation.
4. Verify it at the appropriate boundary.
5. Inspect the artifact or trace, explain the trade-off, and commit.
6. Push the feature branch after verification. Keep publishing PR reviews separate.

The initial branch is `codex/intent-review-foundations`. It builds on
`43acdc7`; existing uncommitted v2.1 work was reviewed and committed first.
The unrelated local `prf_check.py` is deliberately excluded from these commits.

## Slice 1: canonical contracts and compatibility

Read `core/domain/review_contracts.py`, `core/review/requirements.py`, and
`core/runtime/models.py`.

The problem was two independently defined versions of requirement and evidence
records. They used different field names and disagreed about coverage denominators.
Services exchanging those objects could pass their own tests but disagree in production.

The domain module now owns the models. The previous module re-exports the same
class objects. Legacy `*_ids` inputs are accepted as aliases; new domain records
use `*_refs`. The result loader still accepts v2.0 and upgrades it to v2.1.

Pydantic verifies structure and references. It cannot establish that an LLM's
explanation is correct. An evidence record is an auditable observation, not proof
merely because it passes schema validation.

Requirement coverage distinguishes:

- **Verified:** evidence supports the requirement being satisfied.
- **Violated:** evidence supports a violation.
- **Unverified:** assessment was attempted but remains inconclusive.
- **Not assessed:** no assessment was attempted.
- **Not applicable:** excluded with a reason.

Attempt coverage is assessed/applicable. It does not measure correctness. When
there are no applicable requirements the ratio is null, not 100%.

## Slice 2: baseline test debt and source lookup

Read `docs/STAGE_00_BASELINE.md` for historical failures.

The initial current-checkout test run reproduced 511 passes and seven failures.
Those failures expected older product behavior: implicit GitHub approval,
blocking on unattributed test failure, old packaging, and coverage-based clean
recommendations without auditable inspection. Tests were aligned with the current
conservative policy; production gates were not relaxed to satisfy them.

A separate Ruby lookup defect excluded every repository under `/tmp` because it
checked absolute path components. Exclusions now apply to repository-relative
components. This illustrates a backend lesson: validation must use the correct
coordinate system, whether paths, revisions, or tenant identities.

## Slice 3: immutable input and source identity

Read `core/input/snapshot.py` and `tests/test_input_snapshot.py`.

A diff captured at one revision cannot be safely combined with files read from
a later working tree. A mutex reduces concurrent checkout races but is not the
identity of the source itself.

`GitSnapshotProvider` resolves commit references once, hashes the exact diff and
supplied configuration, and reads blobs from those committed trees. A stable
snapshot ID identifies that input. Reads retain the revision and content digest.

The adapter does not check out or import repository code. It rejects escaping
paths, symlink and non-file entries, oversized content, and mismatched snapshots.
Subprocess output is spooled to temporary files before bounded reads into memory.
Git operations have timeouts. This is bounded source retrieval, not an execution sandbox.

The tests use actual temporary Git repositories. They move HEAD and modify files
after sealing the input, then verify that source reads remain pinned.

Current limitations: this provider supports committed trees; it does not capture
staged, unstaged, or untracked changes. The local command compares BASE directly
with HEAD, not automatically with their merge base. Snapshot identity currently
uses the local repository path; cross-clone cache identity remains future work.

## Slice 4: explicit intent through the real review runtime

Read `core/intent/service.py`, `core/agent/bundle_agent.py`, and
`tests/test_intent_runtime.py`.

An explicitly selected JSON file supplies acceptance criteria and exact path
scopes. The loader captures a hash and timestamp, validates limits and unique
IDs, and records the user's supplied requirements as authoritative within that
review scope. It does not auto-discover authority from an analyzed PR.

Relevant requirements reach both discovery and proof construction. Once a defect
passes the existing finding gates, a fresh assessment asks whether it violates
the scoped requirement. A positive assessment records directional HEAD evidence
and a confirmed investigation. The outcome is source-level support, not V3/V4
execution evidence. It remains fallible and needs quality evaluation.

No matching defect leaves the requirement unverified. Absence of findings does
not prove satisfaction. Positive requirement-satisfaction verification and
automatic requirement extraction are not implemented in this slice.

Try an explicitly authored requirements file:

```bash
uv run codeturtle review owner/repo 123 --dry-run \
  --requirements examples/review-requirements.json --json-output outputs/review.json
```

Edit the example's path and acceptance criterion to match the actual reviewed
repository. Never treat its example tenant rule as a universal requirement.

## Slice 5: local committed review and snapshot-bound tools

Read `core/input/tools.py` and `cli/commands/local_review.py`.

The local command uses the same v4 runtime as PR review, with a different input
adapter. It does not introduce a second reviewer engine. Its source and bounded
lexical-search tools read sealed Git objects and never fall back to checkout content.
Checkout-dependent Ruff and risk-signal scans are disabled on this path.

```bash
uv run codeturtle review-local --base HEAD~1 --head HEAD \
  --static-only --json-output .validation/local-review.json
```

`--static-only` makes no model calls. It retains incomplete inspection rather
than inventing successful model assessments. Narrow deterministic defects can
still be reported. This is a useful reproducible demonstration without API access.

Remove `--static-only` to use the configured model provider. An available model
endpoint is required; a failed model call is not a clean review.

Local review does not publish to GitHub or execute repository tests. Lexical
references are labelled lexical references, not resolved call-graph edges.
Truncated/failed tool observations create unresolved context records.

## Slice 6: structural BASE/HEAD analysis

Read `core/intelligence/changes.py` and `tests/test_semantic_changes.py`.

An abstract syntax tree describes source structure. Comparing normalized trees
identifies changed functions, methods, classes, signatures, and module statements
without depending on whitespace or line movement.

The context builder reads both snapshot sides, produces bounded symbol deltas,
and supplies them to the existing investigation. It records parse errors and
omitted scope. Duplicate symbol definitions require explicit investigation
rather than silently overwriting an index entry.

This is structural guidance. It does not establish semantic equivalence, resolve
dynamic dispatch, or prove a regression. Renames are represented as removal and
addition. Context limits are explicit; high recall across repositories is unmeasured.

## Slice 7: verifier output and observability

Read `core/runtime/verify_loop.py` and `tests/test_verifier_response_contract.py`.

Searching anywhere in model text for `VERIFIED` could misread `Not VERIFIED` as
approval. The parser now requires a leading verdict and rejects conflicting
verdicts. Explicit verdicts can still be wrong; parsing correctness is separate
from review correctness.

Provider-backed finding-verifier and requirement-assessor usage now joins agent
usage in canonical provenance. This prevents undercounting those model calls.
Injected test callables do not manufacture provider token telemetry.

## Validation and live diagnostics

Run from Ubuntu WSL in the repository:

```bash
uv run --no-sync python -m pytest -q -p no:cacheprovider
uv run --no-sync python -m tests.evaluation.run_eval --offline
```

The offline command checks stored snapshots. It does not run the current model
against new real PRs. Scripted model tests validate orchestration and contracts,
not defect-detection quality.

The final local foundation validation on November 21 recorded **574 passing
tests** in Ubuntu WSL/Python 3.12, plus four passing stored evaluation snapshots.
Windows/Linux and Python 3.11/3.12 checks are configured in CI; configuring them
does not establish that the hosted jobs have executed successfully.

For an opt-in two-case synthetic live integration diagnostic:

```bash
uv run --no-sync python -u -m scripts.manual.live_intent_smoke \
  --windows-ollama --output .validation/live-intent-smoke.json
```

Use `--windows-ollama` only when running in WSL with Ollama bound to Windows
localhost. It passes JSON through PowerShell stdin, without interpolating prompts
into shell code. Omit it when Ollama is directly reachable in the Python environment.
The report records actual call counts/tokens and includes bridge overhead in latency.
It is a synthetic integration diagnostic, not a held-out benchmark or an inference
performance comparison. The removed-guard case also has an existing deterministic
rule, so its detection cannot be attributed solely to the model.

## Remaining milestones and resume eligibility

The paired analysis tool in `benchmark/paired_analysis.py` consumes adjudicated
per-case counts with explicit clean-control labels. It verifies matched source
identity and reference counts, then resamples related repository/patch clusters
together. Confidence intervals describe uncertainty in measured differences; they
do not repair incomplete labels or development/held-out leakage. See benchmark/README.md.

Actual November 21 live diagnostics are summarized in
`docs/validation/2026-11-21-foundations.json`. The 3B run failed structured proof
generation and misread behavior. The 7B run completed both synthetic cases, with
one deterministic defect and one clean finding list. These runs changed both
model and output cap, so they are not a controlled model comparison. Both ran on
a dirty development checkout and are ineligible for release quality claims.

The foundations and a narrow intent-aware review path are implemented. The complete
2.0 proposal is not finished. Remaining milestones include broader impact context,
explicit requirement satisfaction/counterevidence, durable task recovery, scheduling,
incremental re-review, isolated execution, differential attribution, and real held-out
evaluation with clean controls and adjudication.

Before a resume quality claim, freeze the implementation and dataset; seal predictions
before adjudication; compare matched baselines; report precision and reference-defect
recall together; report clean-PR noise, completion, cost, and latency with denominators.
Keep author-adjudicated labels distinct from independent labels and synthetic cases
distinct from real PRs. Never use test counts as a substitute for detection accuracy.

The next learning checkpoint is to explain why source grounding, requirement
assessment, defect verification, process coverage, and review completion are five
different things, using one saved review artifact.
