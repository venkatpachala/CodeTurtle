# P0/P1 implementation and validation — 2026-09-27

The repository now contains a production-contract preview (`0.5.0a1`). It is
usable for local dry-run reviews and explicitly requested GitHub comments. This
is not a claim that every P0/P1 release gate has passed: hosted Actions, the
new-commit publishing lifecycle, clean benchmark adjudication, and an untouched
held-out quality run remain outstanding.

## What was implemented

### 1. Canonical output and decision policy

`core/runtime/models.py` and `core/review/contract.py` define the schema-versioned
result, exact repository/PR/revision target, stage health, actual unit inspection,
policy reasons, execution evidence, provenance, and verified product findings.
Stable finding fingerprints identify equivalent claims across runs. Diagnostic
candidates remain separate from product findings; an intentionally empty product
list cannot silently fall back to legacy comments.

Terminal rendering, CLI JSON, benchmark scoring, and publication planning consume
this result. JSON writes are atomic and reject non-finite numbers. Failed analysis
has no verdict; partial analysis requires human review. Packed units do not count
as inspected without scoped assessments and evidence references. Unresolved
hypotheses prevent a clean recommendation. Verified blockers can request changes
even when other parts of a review are incomplete. Existing failing tests are
unattributed evidence and cannot independently establish a HEAD regression.

`MERGE` is a recommendation. Publishing maps it to a comment by default;
`--approve` is an explicit, policy-gated option.

### 2. Bounded investigation and proof

The bundle agent requests behavioral deltas, zero to five testable hypotheses,
per-unit outcomes, scoped evidence, and hypothesis-to-proof identifiers. It can
read bounded HEAD source and diff hunks, with path and symlink restrictions. JSON
fence parsing is shared between output parsing and telemetry. Unproven hypotheses
remain visible rather than being discarded as if disproved.

Shared budgets bound model calls, prompt volume, and elapsed checks. A single
bounded proof repair is permitted. Provider timeouts bound individual requests;
an in-flight call can extend beyond the between-call elapsed budget. Ollama now
uses the configured endpoint and correct output-token parameter. OpenAI backend
selection and plain generation are wired, but were not live-tested here.

A narrow AST rule detects removal of a literal zero-denominator guard from an
otherwise identical division function. Its verifier independently derives the
fact from the diff. It abstains on decorators, changed operands, extra branches,
or other unsupported shapes. This is a targeted static proof, not general bug
reasoning or measured benchmark improvement.

### 3. GitHub delivery and operational boundaries

Publication plans validate exact revisions and diff identity, include all verified
findings in the summary, and anchor only valid changed RIGHT-side lines. One
grouped review contains the summary and up to eight inline comments. Plans have
stable markers; replay reconciles already-published reviews rather than blindly
retrying writes. Target and revisions are refreshed immediately before submission.
Publication failures have structured outcomes and a failing CLI exit status.

`--github-auth gh` obtains the local authenticated GitHub CLI credential without
logging it or allowing stale token environment variables to override its keyring.
Clone authentication is passed through ephemeral Git configuration rather than
credential-bearing URLs. Exact checkout revisions are verified. An OS-backed
repository lease covers checkout, analysis, and publication.

Local test execution filters credentials from subprocess environments and disables
automatic pytest plugin loading. It remains trusted-code execution, not an OS
sandbox. Actions reject this execution mode. Cross-machine publication races and
the network interval after a revision check remain limitations.

### 4. Evaluation and release tools

Benchmark metrics score verified product output separately from diagnostic
candidates, track no-verdict cases, and retain null values for undefined metrics.
Product metrics include coverage, abstention, publication outcomes, and paired
regression checks. Missing measurements cannot pass a gate as zero errors.

Frozen cases capture BASE/HEAD identities, input hashes, partition, and patch
lineage. Related lineages must not cross partitions. Prediction sealing uses an
exclusive lock and atomic output. `benchmark.capture` captures real immutable
GitHub inputs; `benchmark.ablate` runs real development-only configuration
experiments and refuses held-out tuning or output overwrites. `benchmark.release`
requires comparable adjudicated reports and a clean, frozen reviewer identity.
Its paired gate is explicitly distinct from held-out certification.

### 5. Packaging, CI, and documentation

The wheel includes `cli`, `core`, and `benchmark`, along with configuration.
Memory storage initializes lazily so CLI help does not create a database at import.
The preview version is `0.5.0a1`.

Action templates use verified commit-pinned actions, audited tooling revisions,
minimal permissions, dry-run defaults, fork restrictions, concurrency, and
retained JSON artifacts. A Windows/Linux, Python 3.11/3.12 validation workflow is
configured. Editing these files does not establish that hosted CI passed.

Current architecture, limitations, release gates, and rollback instructions are
documented separately. Older architecture and shipping documents are marked
historical to prevent their results being attributed to this preview.

## Tests actually run

### No-mock automated selection

Final result: **111 passed in 8.54 seconds**, exit code 0:

```powershell
.venv/Scripts/python.exe -m pytest tests/test_production_contract.py tests/test_phase72_change_units.py tests/test_v4_bundles.py tests/test_v4_reflector.py tests/test_v4_symbols.py tests/test_v4_url_parse.py tests/evaluation/test_scorer.py -q -p no:cacheprovider --basetemp .validation/final-tests
```

This selection uses real value objects, filesystem operations, Git repositories,
subprocesses, actual Python behavior, and policy/metric calculations. Historical
tests containing canned model callbacks or fake clients are excluded from this
no-mock claim. Pure policy tests are not claims of live service integration.
After removing an unused CLI verifier closure, the 50 production contract tests
were rerun and passed in 5.64 seconds. Compilation and `git diff --check` passed.

### Real Ollama and runtime

`scripts/validate_production_live.py` creates actual BASE/HEAD Git commits and
runs the real runtime against local `qwen2.5-coder:7b`:

| Input | Observed result |
|---|---|
| Removed division guard | `REQUEST_CHANGES`, one independently verified AST-rule finding |
| Equivalent multiplication refactor | `MERGE`, complete inspection, zero findings |
| Nonexistent model | Failed run, no verdict; actual provider failure |

Evidence: `.validation/live-rule.json`. Synthetic inputs exercise plumbing and
diagnose behavior; they are not held-out benchmark cases. Earlier repeated traces
showed the model hypothesized the division risk but failed proof construction.
The static rule resolves this narrow case while retaining that model limitation.

An actual external development PR, `ai-code-review-evaluation/discourse-graphite#1`,
was fetched, cloned at its exact revision, and reviewed using real Ollama in
anonymous dry-run mode. It produced two verified rule findings, `REQUEST_CHANGES`,
four inspected units, and eight unresolved hypotheses. Evidence:
`.validation/external-anonymous.json`. This is a diagnostic run, not an
adjudicated quality score.

### Real GitHub publishing

The user supplied CodeTurtle PR #23 for disposable live testing. The real CLI
published a partial-review COMMENT at its recorded HEAD:

- Review: https://github.com/venkatpachala/CodeTurtle/pull/23#pullrequestreview-5329382102
- HEAD: `3e9c9295b36d3768f154a5681cf0575206083af9`
- BASE: `849ca1de93aee4ca01b5c540be121ccf2706344d`
- Evidence: `.validation/pr23-publication.json`

The real delivery validator then confirmed:

- Replaying the exact plan returned `already_published`; review count stayed 3.
- A stale revision was rejected with `reviewed_revision_changed`.
- A different target was rejected with `target_mismatch`.
- A grouped review with a clearly labeled non-defect inline test annotation was
  published: https://github.com/venkatpachala/CodeTurtle/pull/23#pullrequestreview-5329393102
- Replaying that inline plan returned the same review identity without duplication.

Evidence: `.validation/github-delivery-validation.json`. These checks used actual
GitHub APIs, not fake clients. No clean APPROVE or blocker REQUEST_CHANGES was
published on a separate PR fixture. A pushed-new-commit lifecycle and missing-write
permission test were not exercised live.

### Distribution installation

`uv build --out-dir .validation/dist-release` successfully produced the preview
wheel and source distribution. An isolated Python 3.12 environment installed the
real dependency set and final wheel. From `C:\Users\venkat`, outside the source
tree, the installed `codeturtle --help` and `codeturtle review --help` exited 0.
Imports resolved to that environment's `site-packages`, including `benchmark`;
package metadata reported `0.5.0a1`. This checks Windows package installation and
entrypoints, not every platform or the interactive first-run wizard.
The same live runtime script also ran from outside the source tree through the
final installed wheel and actual Ollama. It exited 0 and reproduced the blocker,
clean, and missing-model outcomes. Evidence: `.validation/installed-live.json`,
`.validation/install-validation.json`, and `.validation/installed-review-help.txt`.

### Real Graphify MCP

The installed Graphify extracted a real Python source file into a graph with two
nodes and one edge. CodeTurtle started the actual stdio MCP server, discovered ten
tools, and retrieved graph statistics successfully. Evidence:
`.validation/graph-live-validation.json`. This confirms a small local graph
integration; it does not establish retrieval quality on large repositories.

## Remaining release gates

1. Run hosted validation and the example Action against safe, buggy, and uncertain
   fixture PRs, including forks, denied writes, and a new commit after publishing.
2. Pin the final dependency set and freeze a clean immutable reviewer revision.
3. Add independently adjudicated clean PR controls and complete label evidence.
4. Run paired validation and a genuinely untouched held-out evaluation after the
   release candidate is frozen. Report recall, precision, noise, latency, and
   denominators; do not reuse inspected diagnostic cases as held-out evidence.
5. Validate wizard flows and supported Linux installation. Validate optional
   OpenAI/cloud providers before claiming support was exercised.
6. Provide real OS isolation before enabling arbitrary untrusted test execution.

Use `docs/RELEASE_CHECKLIST.md` for commands and rollout. Current working-tree
changes are reviewable implementation work; a locally built preview is not a
published registry release or evidence of production-quality recall.
