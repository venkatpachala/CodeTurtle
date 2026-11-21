# Source-bound final finding verification

This phase replaces the default model-based final finding gate with a structured,
source-bound decision. It addresses a failure recorded in the preceding phase:
the requirement investigator found a real removed-guard defect, but the final
verifier returned `DISPROVED` without a recorded explanation or source citation.

This is an evidence and reliability improvement. A valid citation establishes
which source the model used; it does not establish that its reasoning is correct.
The measured development results belong in the accompanying validation record.

## The failure and the new path

Consider the following change:

```python
# BASE
def size(items):
    if items is None:
        return 0
    return len(items)

# HEAD
def size(items):
    return len(items)
```

The concrete trigger is `items is None`. BASE handles it; HEAD raises `TypeError`.
If a verifier sees the removed guard in a diff, it may mistakenly treat that guard
as current protection. The old scalar response could reject the finding without
leaving enough evidence to inspect that mistake. The preserved trace establishes
the rejection route, not the model's unrecorded thought process.

The default runtime now follows this path:

```text
Candidate after proof, positioning, and reflection
    -> Read bounded committed BASE and HEAD observations
    -> Request a structured finding decision
    -> Validate the exact trigger and every source citation
    -> Check required HEAD support or HEAD counterevidence
    -> Apply a narrow Python None-flow consistency check when applicable
    -> Accept, reject, or retain an unresolved hypothesis
    -> Store the decision, attempts, claim identity, and observation references
    -> Evaluate product policy
```

Existing deterministic verification routes remain in place. They have their own
narrow structural contracts; this phase does not replace them with model calls.
The low-level legacy verifier remains available for controlled ablations.
`ReviewRuntime` defaults to `finding_verifier_mode="structured"`.

## 1. Separate source observations from interpretation

`GitSnapshotProvider` reads Git blobs at pinned commits. It does not import or
execute reviewed code. Source observations carry revision side, path, line range,
captured text, file digest, excerpt digest, and snapshot identity. A model can cite
these observations but cannot invent another successful tool read.

The final verifier admits at most six paths, 120 lines per file, and 10,000 shared
source characters. The candidate file is first; explicitly declared requirement
`context_paths` can supply dependencies. Missing required HEAD files, truncation,
read failures, and omitted paths result in unresolved verification. This favors
honest incompleteness over unsupported conclusions and limits large-file coverage.

BASE and HEAD are separate prompt fields. They are not merged into a single
undifferentiated diff. Graph text and related test matches are labeled as hints;
they cannot independently reject a candidate on the default structured route.

## 2. Require an inspectable decision

`FindingDecision` contains:

| Field | Purpose |
| --- | --- |
| `verdict` | `supported`, `refuted`, or `unresolved` |
| `checked_trigger` | Exact copy of the candidate's violating condition |
| `rationale` | Concise claim-specific explanation |
| `path_analysis` | Trigger-to-operation path or applicable protection |
| `supporting_citations` | Exact observation IDs, line ranges, and quotes |
| `counter_citations` | Exact counterevidence using the same citation contract |
| `missing_evidence` | Unavailable facts needed to decide |
| `refutation_basis` | HEAD guard, unreachable trigger, equivalent behavior, or preexisting failure |

A supported decision must cite the candidate's offending operation in complete
HEAD source. A refuted decision must cite active HEAD counterevidence outside
tests. BASE-only guards and test names are insufficient. Preexisting-failure or
equivalent-behavior attribution additionally requires BASE evidence. Any declared
missing evidence prevents a conclusive verdict.

Citation validation checks retrieved identity, inclusive line bounds, and exact
text, including indentation. The trigger must match exactly. A bare `VERIFIED`
or `DISPROVED` is invalid under this contract.

## 3. Use a small deterministic check where its assumptions are explicit

`core/verification/reachability.py` parses Python with `ast`; it never runs source.
For a narrowly recognized direct None trigger and a unique operation line inside
a unique undecorated function, it can follow simple `is None` / `is not None`
branches and early returns or raises.

If the known None input reaches `return len(items)`, a historical guard cannot
refute it. If an active HEAD guard returns first, the verifier cannot support the
claimed failure at that operation. Unknown conditions, assignments, loops,
decorators, ambiguous functions, and unsupported syntax return unknown. This is
not a general symbolic executor, type checker, or new defect discovery rule.

Other triggers and languages continue to rely on bounded model reasoning and
validated citations. Even the narrow check does not establish whole-program
correctness, external caller reachability, or the truth of supplied requirements.

## 4. Bound repair, failures, and cost

The verifier uses at most two attempts: the initial response and one protocol
repair containing the validation error and the same source package. It repeats
all checks after repair. It never upgrades an invalid response by extracting a
verdict word from it.

Every attempt reserves the shared review budget. The prompt admission cap is
24,000 characters; recorded response text is capped at 16,000 characters. The
default gateway request permits 1,400 output tokens with no transport retry.
The injected experiment adapter records its own actual requests and token usage.

Records distinguish `completed`, `invalid_response`, `provider_error`,
`internal_error`, `budget_exhausted`, and `context_unavailable`. A successful
request returning unresolved evidence is a completed assessment; malformed output
or infrastructure failure degrades review health. Neither creates a product
finding. Static-only mode does not make model requests.

The shared elapsed-time limit is checked between requests. It is not a hard
deadline capable of cancelling an already-running provider request.

## 5. Preserve the claim and publication target

`FindingVerificationRecord` stores the typed candidate claim, its SHA-256
fingerprint, snapshot identity, observation references, validated decision, hints,
and each attempt's prompt digest and response. These records are included in
canonical result schema `2.3`. Stored `2.0`, `2.1`, and `2.2` results remain readable.

Deserialization validates observation revisions and digests, citation references,
claim fingerprints, and correspondence between a verification and its published
finding. A decision cannot be attached to a different expected/actual behavior
merely because its file and trigger match. Supported final citations become
explicit evidence records linked to the product finding.

GitHub PRs introduce another distinction: the target branch can advance after a
feature branch diverges. `base_sha` remains the target tip required for publication
identity. `comparison_base_sha` records the merge-base used for historical source
reads. This avoids treating unrelated later target changes as part of the PR.
Local direct comparisons preserve their previous default semantics and IDs.

In PR mode, this phase captures pinned source for the final verifier from the
existing repository checkout. It does not replace the entire PR input pipeline
with the local snapshot adapter or add a network fetch when objects are missing.

## 6. Test mechanisms separately from model quality

The focused tests use temporary real Git repositories and scripted responses.
They exercise removed/preserved guards, invalid quotations, wrong triggers,
BASE-only evidence, unrelated guards, ambiguous paths, bounded repair, exhausted
budgets, transport errors, graph/test hints, result tampering, and divergent PR
branches. Scripted agreement verifies the mechanism, not model accuracy.

Run from PowerShell in this WSL-backed project:

```powershell
wsl.exe -d Ubuntu --cd /home/venkat/projects/CodeTurtle .venv/bin/python -m pytest tests/test_comparison_snapshot.py tests/test_source_finding_verifier.py tests/test_finding_verification_runtime.py tests/test_requirement_experiment.py -q -p no:cacheprovider
```

The experiment harness independently varies intent strategy and final verifier
mode. Multiple verifier modes produce names such as `investigate:legacy` and
`investigate:structured`. Both variants use the same materialized commits and
source input ID, while configuration snapshot IDs distinguish the mode. Execution
order alternates by case to reduce systematic warm-model bias.

Predict from a clean frozen checkout, seal outputs, then load labels separately
for scoring. For example, in WSL with Ollama running on Windows:

```bash
python -m benchmark.requirement_experiment \
  --output /absolute/path/to/new-run \
  --windows-ollama --strategies investigate \
  --verifier-modes legacy structured \
  --case none-guard-removed --case none-guard-preserved
python -m benchmark.requirement_score /absolute/path/to/new-run
```

The scorer checks artifact seals, annotation hashes, source pairing, and complete
variant membership. It reports requirement-outcome matches, product findings,
health, verifier statuses, repairs, requests, reported tokens, and elapsed time.
Citation grounding and semantic truth remain separate. Synthetic author-labeled
development cases are not independent held-out evidence; headline precision and
recall intentionally remain undefined.

## Learning sequence and next phase

Read the implementation in this order:

1. `core/domain/finding_verification.py`: model the claim and decision before orchestration.
2. `core/input/snapshot.py`: understand pinned revisions and merge-base identity.
3. `core/verification/source_verifier.py`: follow capture, prompt, validate, repair, record.
4. `core/verification/reachability.py`: identify every assumption in the narrow check.
5. `core/runtime/verify_loop.py`: locate deterministic routes and structured dispatch.
6. `core/runtime/review_runtime.py`: trace health, evidence, product findings, and policy.
7. `benchmark/requirement_experiment.py` and `requirement_score.py`: reproduce paired evaluation.

Trace one `size(None)` candidate through its claim fingerprint, source observations,
decision, evidence record, final finding, and serialized result. Then change one
quoted character and explain why the result becomes unresolved. Repeat with an
active HEAD guard, a BASE-only guard, and a missing dependency file.

The next priority is a small adjudicated real development-PR corpus and failure
analysis under matched model settings. Use that evidence to guide better scoped
context retrieval and output reliability. Complete the common PR snapshot adapter
before durable execution and dependency-aware re-review. A task queue, LangGraph,
or extra agent roles would not by themselves fix unsupported verification.
