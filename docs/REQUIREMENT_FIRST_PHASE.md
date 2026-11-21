# Requirement-first evidence assessment

This phase extends the existing reviewer with requirement-driven investigation
over sealed local committed inputs. It retains the finding gates and separates
source observations from model interpretation. It is not a completed CodeTurtle
2.0 release or a demonstrated real-PR quality improvement.

## The problem this phase solves

The foundation path supplied requirements to discovery and linked an already
verified defect to a relevant requirement. If discovery returned no candidate,
the later assessor had no defect to examine. The system could therefore miss a
requested behavior without actually investigating it.

The new path plans one task per supplied requirement independently of discovery:

```text
Explicit requirement and exact path scope
    → Bounded BASE/HEAD observations
    → Structured investigator proposal
    → Exact citation validation
    → Fresh structured challenge
    → Candidate or bounded satisfaction support
    → Existing finding gates for proposed defects
    → Canonical requirement assessment, evidence, and run diagnostics
```

For example, removing a `None` guard from `size(items)` can be investigated even
when the general discovery conversation returns no candidates. Tests demonstrate
that integration with scripted responses; live diagnostics remain separate evidence.

## 1. Observations describe what the tools actually read

`core/domain/observations.py` defines `SourceObservation` and `SourceCitation`.
`core/intent/observations.py` captures source from `GitSnapshotProvider`.

An observation records the snapshot, revision, side, path, inclusive line range,
captured text, full-file digest, excerpt digest, and availability status:

- `success`: the entire file was captured within limits.
- `truncated`: only part was captured.
- `absent`: the exact committed tree has no such path.
- `error`: reading or decoding failed.

The default collector admits at most six distinct paths, 120 lines per file,
and 18,000 source characters shared across the requirement's BASE/HEAD reads.
Omissions and truncation remain explicit gaps. Missing declared context cannot
be turned into evidence that no protection exists elsewhere.

A citation must reference a retrieved observation and reproduce exactly the
specified lines, including indentation. Unknown IDs, wrong line ranges, altered
quotes, and citations to unavailable observations are rejected. The model cannot
create a new source observation by describing one in its response.

This establishes source grounding, not logical correctness. Two models can still
misinterpret valid code. That is why source validity and adjudicated claim correctness
must remain separate metrics.

## 2. Planning and structured model decisions

`core/intent/investigator.py` owns requirement planning and the two model stages.
Requirements support optional `context_paths` for explicitly supplied protection
or dependency files outside the primary paths. These paths are not an automatic
call graph; missing indirect dependencies remain a limitation.

Each stage returns a `RequirementDecision` with:

- The requirement ID and `violated`, `satisfied`, or `unresolved` outcome.
- Rationale and the bounded `checked_scope`.
- Exact supporting citations and inspected counterevidence.
- Missing evidence.
- For violations: a concrete trigger, expected/actual consequences, symbol,
  execution path, severity, and precise HEAD anchor.

A conclusive decision needs valid complete HEAD evidence and no declared missing
evidence. A violation must cite scoped HEAD code and BASE evidence when a baseline
file exists. It must identify the actual offending HEAD line in a changed scoped
path. The fresh verifier receives structured observations and the proposal, not
the entire discovery conversation. Disagreement remains unresolved.

The prompt includes the citation field schema and line-numbered source. Merely
asking for JSON is insufficient when the model does not know the schema. We found
that problem in the first live development attempt and preserved the failure.

Each stage permits one protocol-repair attempt with validation feedback and the
same observations. Every attempt reserves the shared budget and repeats citation
checks. A second invalid response becomes an explicit error; provider failures
retain error status. A shared budget exhaustion before
a model request produces `not_assessed`; exhaustion during an investigation leaves
it unresolved. Admission limits preserve a record for deferred requirements.

## 3. Findings still pass the existing gates

Requirement agreement never directly appends a product finding. A proposed defect
becomes an ordinary `Candidate` associated with its scheduled bundle and goes through:

```text
Classification → Proof gate → Positioner → Reflector → Verify loop
```

`core/intent/adjudication.py` promotes a requirement violation only when that
candidate survives those gates. A dropped candidate leaves the requirement
unverified. This prevents the new subsystem from bypassing existing policy.

A bounded satisfaction assessment can become requirement status `verified` after
the two structured stages and citation checks. The investigation hypothesis is
"the change violates the requirement," so its corresponding status is `disproved`.
That does not mean the requirement itself was disproved.

Every conclusive assessment is labelled source-level support in its recorded
scope. It is neither runtime reproduction, differential attribution, formal proof,
nor a guarantee covering all possible executions. It does not automatically increase
source-unit inspection or make a clean recommendation eligible.

## 4. Canonical result 2.2

`ReviewResult` now includes `source_observations`; `EvidenceRecord` can reference
those observations. Validation checks revision identity, snapshot identity,
availability, excerpt digest, and evidence direction at the product boundary.
Both aggregate domain containers now share the investigation-resolution direction
check instead of independently accepting unrelated resolution evidence.

Structured requirement runs, proposals, verifier responses, gaps, and reasons
remain in provenance. Source observations remain typed top-level records. Historical
2.0 and 2.1 results still load and upgrade to 2.2 with empty observation defaults.

The result loader reconstructs artifacts; it does not implement durable task resume.
SQLite checkpoints and dependency-aware reuse remain future milestones.

## 5. Run the new path

From Ubuntu WSL at the repository root:

```bash
uv run codeturtle review-local --base HEAD~1 \
  --requirements examples/review-requirements.json \
  --requirement-strategy investigate --json-output .validation/review.json
```

The local default is `investigate`. Two ablations are available:

- `link`: preserve the foundation's finding-to-requirement association.
- `off`: exclude intent from investigation and mark requirements not assessed.

`--max-requirements` controls admission, with a default of eight. All model stages,
including injected finding verifiers, reserve the shared review budget. Actual
provider tokens remain separate from character estimates and logical reservations.

`--static-only` skips model investigation and requirement assessment, records zero
model reservations, and preserves incomplete inspection. It never calls a provider
to try to strengthen a static candidate.

The GitHub PR command retains its existing `link` behavior. The new investigator
requires a sealed snapshot; unifying remote PR input, merge-base semantics, and
snapshot-bound tools is a remaining integration task, not an implicit fallback.

## 6. Frozen development corpus and experiment protocol

`benchmark/datasets/requirement_development_v1` contains twelve author-labelled
synthetic cases: six defects, five clean/intentional changes, and one unavailable
external-policy case. Inputs, labels, and hash manifest are separate files.

The prediction loader reads only the manifest and inputs. It works even when
`labels.json` is absent. Synthetic corpora are excluded from the existing registered
real-PR split loader, preserving that loader's disjointness checks.

```bash
uv run python -u -m benchmark.requirement_experiment \
  --windows-ollama --limit 2 --output .validation/requirement-experiment

uv run python -m benchmark.requirement_score \
  .validation/requirement-experiment
```

Use `--windows-ollama` only for the explicit WSL-to-Windows localhost transport.
Omit it for an endpoint reachable directly from Python. This adapter is for local
experiments, not an added production provider dependency.

The runner creates one temporary committed repository per case and reviews the
same source in each selected mode. It alternates strategy order across cases,
preserves partial progress, refuses to overwrite a run, and seals predictions
before the separate scoring command opens annotations. Completed outputs record
reviewer commit/dirty status, corpus hashes, source identity, budgets, model
requests, token counts when available, failures, and elapsed time.

Scoring validates the seal and annotation hashes, all required assessments,
paired source identity, and complete case/strategy membership. It reports outcome
matches and resource measurements with denominators. It deliberately leaves
real-PR precision and recall undefined. The `link` comparison is a same-commit
ablation, not a historical v4 experiment.

These are development cases used to build the system. They are not independently
adjudicated real PRs, held-out data, or resume headline evidence. Model tags are
recorded; immutable model artifact identity still needs stronger provenance.
Character-based admission is not an exact model-token limit. Production context
profiles and provider truncation detection need further work before claiming
complete model attention to every captured observation in larger repositories.

## Learning walkthrough

The phase's [recorded validation summary](validation/2026-11-21-requirement-first.json)
includes the cancelled initial development attempt and both complete diagnostic
runs. Full sealed artifacts are preserved under `validation/requirement-first-v2`
and `validation/requirement-first-v3` so the result can be inspected and rescored.

The full local suite passed 610 tests, including 36 additional tests in this phase;
four stored offline evaluation snapshots also passed. These are implementation
checks, not a measured real-PR accuracy score. Hosted matrix execution is not
claimed from local validation alone.

The complete v3 diagnostic used frozen clean reviewer commit `4109f2f`, two synthetic
cases, and the same installed 7B model for both modes:

| Measurement | Link | Investigate |
| --- | --- | --- |
| Completed reviews | 2/2 | 2/2 |
| Requirement outcomes matching development labels | 0/2 | 1/2 |
| Actual model calls | 2 | 7 |
| Reported prompt tokens | 1,225 | 7,269 |
| Reported completion tokens | 214 | 1,542 |

The investigator produced a grounded candidate for the removed `None` guard,
but the existing final finding verifier rejected it. The expected violation
therefore stayed unverified. The preserved guard received bounded satisfaction
support. This demonstrates the new path's mechanics and a specific false-negative
bottleneck; it does not demonstrate improved defect recall. The protocol repair
mechanism is tested separately; the v3 live responses did not need a repair.

Rescore the preserved artifact without model calls:

```bash
uv run python -m benchmark.requirement_score docs/validation/requirement-first-v3
```

Read these files in order:

1. `core/domain/observations.py`: distinguish observation identity from interpretation.
2. `core/intent/observations.py`: inspect bounded capture and incomplete outcomes.
3. `core/intent/investigator.py`: trace planning, grounding, budgets, and fresh challenge.
4. `core/intent/adjudication.py`: explain why agreement is not enough to publish a finding.
5. `core/runtime/review_runtime.py`: locate the integration before finding gates and policy.
6. `benchmark/requirement_experiment.py` and `requirement_score.py`: trace prediction sealing.

Follow one task through planned, proposed, verified/disagreed, and final canonical
state. Then change a quote, remove a context file, exhaust the budget, and reject
the candidate in the finding verifier. The tests show how each failure remains
observable without becoming an unsupported conclusive assessment.

## Next work

Inspect live diagnostic failures before enlarging the architecture. Improve
structured-output reliability under matched model settings, then expand to
adjudicated real development PRs. Complete the shared snapshot input adapter for
GitHub PR mode. Only then add durable task recovery and dependency-aware re-review
against stable input and evidence identities. Broader impact resolution, duplicate
consolidation, isolated execution, and held-out release qualification remain open.
