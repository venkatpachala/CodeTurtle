# CodeTurtle vNext Stage 00 baseline

Recorded on 17 November 2026 in Ubuntu WSL.

## Baseline and environment

- Baseline commit: `8da178159730cacec38f3b37805be3428ed5b8c0`.
- Original checkout: `/home/venkat/projects/CodeTurtle` on `feat/verification-runtime`. The working tree already had an edit to `uv.lock`.
- Stage worktree: `/home/venkat/projects/CodeTurtle-intent-aware-review` on `feat/intent-aware-review`, created directly at the baseline commit.
- System Python: 3.14.4. Both worktrees use a Python 3.12.16 virtual environment. uv 0.13.7 and pytest 9.1.1 were verified.
- The existing `.venv/bin/python -m pytest --version` already succeeded. A direct WSL invocation could not find `uv` on its PATH. `bash -lc` loaded the login PATH and resolved `uv`.
- The committed lock resolves the dependencies but has stale schema and editable-package metadata. `uv sync --frozen --python 3.12 --group dev` installed the baseline for testing. After baseline validation, an offline sync refreshed the lock revision from 3 to 5 and the editable package version from `0.4.0` to `0.5.0a1`. Dependency pins are identical. `uv lock --check --offline` then passed.

The lockfile-only commit is `395d0ef8ec9fdd709bd086df93d5e636a0cfe099`, directly after the immutable baseline. Inspect its exact diff with `git show 395d0ef -- uv.lock`.

## Validation

Run these commands from the repository root. The recorded baseline used the isolated Stage worktree at the baseline commit. `--no-sync` uses the installed environment for the checks.

| Check | Result |
| --- | --- |
| `uv run --no-sync python -m pytest --version` | Exit 0, pytest 9.1.1 |
| `uv run --no-sync python -m pytest -q` | Exit 1, 482 passed, 9 failed, with one invalid-escape warning from `evals/runner.py` on first import |
| `uv run --no-sync python -m pytest -q --tb=no --basetemp .venv/stage00-pytest-home` | Exit 1, 484 passed, 7 failed |
| Production workflow test selection below | Exit 0, 111 passed |
| `uv run --no-sync codeturtle --help` and `uv run --no-sync codeturtle review --help` | Both exit 0 |
| `uv run --no-sync python -m tests.evaluation.run_eval --offline` | Exit 0, 4 fixture snapshots passed: `deepeval-3288`, `qw-538`, `qw-571`, `v4-synthetic` |
| Controlled v4 runtime on a one-file Python diff | Exit 0, one verified blocking finding and `REQUEST_CHANGES` |

```bash
uv run --no-sync python -m pytest tests/test_production_contract.py \
  tests/test_phase72_change_units.py tests/test_v4_bundles.py \
  tests/test_v4_reflector.py tests/test_v4_symbols.py tests/test_v4_url_parse.py \
  tests/evaluation/test_scorer.py -q -p no:cacheprovider
```

The offline evaluation scores recorded snapshots. The controlled v4 run exercised the runtime directly with a scripted empty discovery response and an unused scripted verifier. It diffed a function that returned zero for a zero denominator against a version that executes division unconditionally. The deterministic verifier produced one medium, blocking, verified defect at `app.py:2`. The serialized result had schema `2.0`, completed health, one eligible unit, zero inspected units, and the policy reasons `verified_blocker` and `insufficient_inspection`. The production contract tests also execute both variants and confirm the changed behavior. Live providers, GitHub review delivery, and hosted CI were outside this baseline.

### Baseline failures

The first five rows enumerate the seven failures reproduced with the fixture root outside `/tmp`. The final row records the two separate Ruby lookup failures reproduced with pytest's default temporary root. Compare Stage 01 results against the same fixture location and test IDs.

| Count | Failing checks | Diagnosis |
| --- | --- | --- |
| 1 | `test_packaging.py::TestPyproject::test_project_name_and_version` | Hardcoded `0.4.0` expectation from before the project version became `0.5.0a1`. |
| 3 | `test_phase43_execute.py::TestExecuteHappyAndFail::test_fake_pytest_fail_policy_request_changes`, `test_phase43_execute.py::TestGraphAndPolicy::test_execution_report_failed_requests_changes`, `test_v4_sandbox.py::TestSandboxResults::test_mocked_exit_1_request_changes` | Expect `REQUEST_CHANGES` for a failing execution without defect attribution. The current policy requires a verified blocker and returns `COMMENT` for these cases. |
| 1 | `test_v4_runtime_smoke.py::TestRuntimeSmoke::test_empty_agent_still_calls_policy` | Compares the v4 verdict with legacy `decide()` using bundle coverage. v4 uses health and auditable inspection. The fixture returns `COMMENT` with `partial_analysis`. |
| 1 | `test_phase61_github_post.py::TestEventsAndClamp::test_538_request_changes_supported_zero_is_comment` | Expects implicit `APPROVE` when the recommendation is `MERGE`. The current delivery contract requires explicit approval and eligibility. |
| 1 | `test_phase63_action.py::TestWorkflowFile::test_example_yaml_present` | Expects a `dependabot[bot]` string. The current example gates automatic analysis by same-repository origin and draft state, with publication controlled by manual dispatch. |
| 2 | `test_risk_signals.py::test_structural_contract_and_dataflow_signals`, `test_risk_signals.py::test_callee_contract_returns_bounded_dispatcher_evidence` | Both Ruby lookup paths apply excluded directory names to absolute `path.parts`. A checkout under `/tmp` therefore skips all matching Ruby files. Both cases pass with a fixture root outside `/tmp`. This is a baseline lookup defect. |

## Architecture inventory

| Boundary | Current behavior at the baseline | vNext integration |
| --- | --- | --- |
| [ReviewRuntime](../core/runtime/review_runtime.py#L320) | `ReviewPipeline` supplies a frozen PR context. The sequential runtime builds a diff index, change units and bundles, runs deterministic rules and bundle investigations, grounds and verifies candidates, collects execution and inspection records, and evaluates policy once. | Keep the entry point and frozen-input checks. Feed resolved requirements into planning before investigation when the vertical slice needs them. |
| [ReviewResult](../core/runtime/models.py#L136) | Canonical schema `2.0` includes target SHAs and diff hash, health, inspection, diagnostic findings, verified product findings, execution, trace, provenance, and policy reasons. CLI JSON and benchmark adapters consume the contract. | Introduce versioned intent, requirement, investigation and evidence contracts with backward-compatible serialization. |
| [BundleAgent](../core/agent/bundle_agent.py#L334) | Runs bounded discovery, evidence retrieval and proof generation. It can attempt one proof repair within its step cap and uses the shared [`ReviewBudget`](../core/review/budget.py) for model calls. | Reuse bounded tools and budgeting. Requirement analysis needs source-grounded criteria and an independent assessment of satisfaction. |
| [Proof Gate](../core/agent/contract.py#L85) and [Verify Loop](../core/runtime/verify_loop.py#L287) | Proof requires a claim, code excerpt, invariant and violating condition. The Verify Loop checks source grounding and counterevidence, then uses a supported deterministic proof or the bounded verifier path. | Preserve the finding gates. Introduce referential validation and adjudication for requirements and revision-bound evidence. |
| [Policy](../core/review/contract.py#L78) | Failed or skipped analysis yields a null decision. A verified blocker requests changes even with partial analysis. Incomplete inspection, unresolved work and unattributed failures produce `COMMENT`. A complete clean review can recommend `MERGE`. | Preserve existing verdict semantics for callers. Keep requirement status, hypothesis status, inspection and run health independently representable. |

The compatibility graph remains explicit. The current [inspection collector](../core/review/inspection.py#L12) tracks source and test change units. Its counts describe process coverage, so Stage 01 needs a distinct requirement coverage contract.

## Stage 01 handoff

Extend the canonical result through its existing serializer and CLI adapter. Preserve the shape expected by current CLI JSON and benchmark consumers, including empty verified output and null decisions. Validate requirement-to-source and claim-to-evidence references, retain immutable revision provenance, and reject impossible state combinations. Agree on the schema version and additive migration with the Stage 01 contract tests.

The Stage 00 exit gate is met with the recorded test debt. The development branch and environment are ready, and existing review and verdict behavior is reproducible.
