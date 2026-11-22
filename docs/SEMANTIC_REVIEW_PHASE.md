# Semantic review controls and honest merge-safety metrics

Validated on 2026-11-22 at reviewer `cd857b0c5f38c70e330101473006bb85e6c06240`.
This is a development milestone, not completion of CodeTurtle 2.0 or evidence
of arbitrary-PR accuracy. The default local model remains `qwen2.5-coder:7b`.

## What changed and why

Previously, a hypothesis describing a correct edit could become a defect candidate.
Nonempty expected/actual fields and a diff location established structure, not a
regression. A later snippet gate sometimes discarded the candidate before the final
source verifier ran. Passing protocol tests did not establish useful native review.

The native path now distinguishes three records:

1. A **change assessment** describes a delta, an expected contract, its authority,
   an outcome, and missing evidence. A repair or behavior-preserving refactor can
   be recorded without inventing a defect hypothesis.
2. A **regression lead** supplies a concrete trigger and distinct expected and
   suspected outcomes for the same property. Source inference remains an assumption.
3. A **regression proof proposal** compares BASE satisfying that contract against
   HEAD violating it. The backend resolves operation text from admitted source
   IDs and line ranges. It does not accept a model-written code quotation.

These records are structurally validated; their semantic claims are not thereby
proved. A supported proposal becomes a provisional Candidate. Existing location,
reflection, and independent final source-verification gates still apply.

`core/agent/semantic.py` implements this protocol. Important boundaries:

- The provider schema expresses consistent-change / suspected-violation /
  unassessed branches. A potential regression requires a lead.
- When no user requirements exist, the schema does not offer explicit requirement
  authority. Supplied requirement IDs are checked again by the backend.
- Discovery admits at most four units per bundle, two per request, whole excerpts
  of at most 2,500 characters, and at most 9,500 excerpt characters in total.
  Related test excerpts are context, not executed evidence or extra inspected units.
- Discovery permits three requests and one shared repair within the four-step
  bundle limit. After a truncated response, repair shrinks to one unit. Invalid
  siblings cannot erase valid assessments or indefinitely starve later units.
- At most two leads are investigated. Deferred units/leads and shared-budget
  exhaustion remain explicit. These caps currently limit large-PR usefulness.
- Proof ranges select at most six captured source lines. Wrong-side, foreign,
  unavailable, or out-of-range references are rejected. Only evidence actually
  admitted to the proof package can support the proposal.
- Expected behavior already present in HEAD, unchanged BASE/HEAD behavior, and
  BASE not satisfying the proposed contract cannot establish an introduced defect.
- `core/verification/literal_facts.py` rejects contradictions against a single
  direct named Python scalar assignment or keyword. It abstains for computed or
  ambiguous values and other languages. It is not a Python/Rust interpreter.

`SnapshotBundleTools.read_source` now accepts BASE or HEAD and records the side.
Per-unit inspection progress survives a failed sibling investigation. Contract
gaps and tool limitations include IDs, paths, scope, and relevant dependencies.
Model self-refutation remains unresolved until independently established.

The normal CLI uses this semantic protocol. Historical injected `llm=` callbacks
retain the legacy wire protocol for compatibility; semantic callback tests select
`discovery_protocol="semantic"` explicitly. Provenance records the actual profile.
There is no native parse-failure fallback to the legacy protocol.

## An integration defect found by the positive control

The new end-to-end native HTTP test generated an introduced `len(None)` regression,
resolved its exact source operation, and reached the independent narrow source
rule. Publication then failed because `FindingClaim.existing_code` stripped source
indentation while the published finding retained it. The signed claims differed.

The fix preserves exact operation whitespace and rejects blank-only operations.
The positive control now reaches one verified product finding and
`REQUEST_CHANGES`; rejecting every candidate cannot satisfy this test. The HTTP
service is controlled test infrastructure, not a measurement of model reasoning.
Model scores are now labeled **uncalibrated**, rather than displayed as a
percentage that could be mistaken for measured correctness probability.

## Benchmark truth and safety reporting

An empty issue list no longer establishes a clean PR. The dataset accepts optional
typed `pr_truth` records with defective/reviewed-clean/uncertain labels, exact
BASE/HEAD, named labelers, evidence, and rationale. A truth record must match the
prediction target. Known supplied issues establish a defective case within that
label set; provisional source labels still require adjudication before headline use.

Normal run, sealed scoring, and recomputation pass this metadata to evaluation.
Aggregate reports include:

- `false_merge_given_defective`: defective PRs recommended MERGE / labeled defective
  PRs, including explicit no-verdict artifacts in that denominator.
- `defective_given_labeled_merge`: defective PRs recommended MERGE / MERGE
  recommendations with defective or reviewed-clean labels.
- Uncertain/unlabeled MERGEs, no-verdict counts, raw event/total counts, and
  two-sided 95% Wilson intervals. Possible label bounds are reported separately
  from statistical confidence intervals.
- Unknown cases excluded from clean-PR counts and clean decision expectations.
- Release gates requiring PR truth completeness and a measured false-MERGE upper
  interval bound, in addition to existing quality, sample, reliability, and latency
  requirements. Missing measurements cannot pass.

The metric cohort is paired prediction artifacts. Infrastructure failures without
a prediction artifact remain in run manifests and block sealed-run completeness;
they are not silently counted as successful reviews. This change does not create
the missing real-PR labels or independently adjudicate them.

For example, 0/10 observed errors has a 95% Wilson upper bound of about **27.8%**;
0/400 has an upper bound of about **0.95%**. Neither observed rate establishes zero
risk. The interval assumes independent representative cases; related patches,
repeated seeds, and multiple revisions are not independent samples.

## Implementation commits

| Commit | Change |
| --- | --- |
| `c01abed` | Typed assessments, BASE/HEAD proof proposals, exact source references, contradiction checks, per-unit progress |
| `574e30c` | Actual protocol provenance and uncalibrated score labels |
| `348420a` | PR truth, both safety denominators, Wilson intervals, scorer/report/gate integration |
| `69dc4f5` | Smaller local-model batches and truncation repair |
| `5545c63` | Coherent provider schema, failure isolation, related test context, local CLI admission controls, CI coverage |
| `cd857b0` | Exact claim/source whitespace, scoped requirement authority, native end-to-end positive control |

## Actual validation and unsuccessful attempts

The [artifact manifest](validation/semantic-review-v1/manifest.json) records hashes,
reviewer/model identities, frozen source identities, reference scope, and CI.
Raw review JSON and driver records are retained beside it. Earlier failed profiles
are retained rather than replaced with successful runs.

| Run | Result | Recorded inspection | Elapsed |
| --- | --- | ---: | ---: |
| Original #53342 baseline, `b849f18`, GitHub CLI | COMMENT, zero validated findings | 31/94 | 162.2 s |
| Initial semantic GitHub attempt | Rejected because the live PR moved from frozen SHAs | No analysis | 2.5 s |
| Initial pinned semantic profile, `574e30c` | NO VERDICT; discovery truncation and exhausted work | 0/92 | 311.6 s |
| #53337 profile v2, GitHub CLI | NO VERDICT; inconsistent hypothesis contracts | 0/3 | 90.1 s |
| #53337 profile v3, clean local CLI | COMMENT, partial | 1/3 | 68.5 s |
| Original #53342 profile v3, clean local CLI | COMMENT, partial; 12 model requests | 18/82 | 196.3 s |
| #53337 final profile, clean local CLI | COMMENT, partial; 3 model requests | 3/3 | 50.0 s |
| Latest #53342 final profile, clean GitHub CLI dry-run | COMMENT, partial; 8 model requests | 12/79 | 113.9 s |

These are development iterations with different profiles, admission caps, intake
paths, and diff inventories. They are **not a matched A/B latency or quality
experiment**. Elapsed values come from drivers; model/runtime timings are distinct.
Inspection counts measure accepted assessment records, not proven understanding
or semantic recall. The iterations represent only **two underlying PR families**.

Final reviewer: **773 local tests passed**. The [hosted contract matrix](https://github.com/venkatpachala/CodeTurtle/actions/runs/44998406823)
passed Windows/Linux and Python 3.11/3.12, including new semantic and safety tests.
The hosted matrix runs selected contract suites; it is not four repetitions of
all 773 local tests.

## Source-grounded case analysis

For #53337, comparison BASE is `c030ffb6b9c7a1b49072dceca1c2224cdfc21bcc`
and HEAD is `ae0ac16cec6e2ba89c5814f3d1d936db90317582`.
At `litellm/batches/main.py:882`, HEAD uses the plural `list_batches` in an error
message. At line 891, the synthetic `httpx.Request` stored on the error uses `GET`
instead of `create_thread`. This metadata repair is not a newly broken outbound
network operation. The earlier model reversed or misclassified the repair.

The final native run recorded all three units, produced no candidates, and had no
schema errors. It still proposed a questionable lead about the added test, then
self-refuted it. Missing bounded test-source context and unverified self-refutation
kept the overall result partial with three unresolved entries. This is better
handling of the observed case, not proof that the model no longer confuses repairs.

For latest #53342, target BASE is `5f5b378a3a998f3278efa8e7b9f90c46093bf677`
and HEAD is `3ace05125c1ca8e186c42bfc51f2b98f223c34c5`.
The GitHub dry-run recorded 12/79 eligible units, zero candidates, zero final
findings, and eight unresolved entries. Its four bundles and per-bundle admission
caps leave major scope uncovered even with model requests remaining. It is not
an adequate complete review of this 47-file Rust refactor.

## Independent GPT comparison

Two independent CLI reference runs used **`gpt-6-astra`**, one per captured #53342
revision. Reference packets contained all 47 changed-file patches and selected
BASE/HEAD sources with explicit clipping; they contained no CodeTurtle predictions
or other reviewers' comments. Repository/AGENTS text was designated untrusted data.
No repository code or tests were executed.

The original reference covers HEAD `6288812fe4c81b7c9ed59a24e190cd6e19464701`;
the latest reference matches `3ace05125c1ca8e186c42bfc51f2b98f223c34c5` from the
final GitHub run. Both reference outputs found no demonstrated introduced defect
and retained unresolved contracts. That does not establish a reviewed-clean label.

In particular, removed authorization checks cannot automatically be reported as
a reachable native restricted-key bypass: the supplied native host's key row type
is `Infallible`. Other host consumers, master-key prechecks, admission behavior,
compile completeness, and clipped tests remain unresolved. No Rust build/test
result is claimed by this harness.

Reference context is broader than the bounded local review; model and context
effects are confounded. The main implementer saw earlier bot feedback; only the
reference packet boundary was isolated. GPT outputs are model opinions, not gold
labels or an independent human audit. CLI aggregate token reports were 85,120 and
82,889; these are not billed-cost measurements.

Requested alternatives `gpt-6.2-sol`, `gpt-6.2-astra`, `gpt-5.3-codex`, and
`gpt-6-sol` were rejected by the available account route as unsupported. They are
recorded as unavailable attempts, not successful comparisons with additional models.

## Reproduction and remaining work

Run software checks in WSL from the project root:

```bash
.venv/bin/python -m pytest -q
.venv/bin/python -m pytest tests/test_semantic_review.py tests/test_gateway_http.py tests/test_merge_safety_metrics.py -q
.venv/bin/python docs/validation/semantic-review-v1/summarize.py
```

Raw driver JSON records the exact commands and revisions. For pinned local review,
use an existing repository containing the captured Git objects:

```bash
.venv/bin/python -m cli.main review-local \
  --repo ~/.codeturtle/repos/BerriAI_litellm \
  --base c030ffb6b9c7a1b49072dceca1c2224cdfc21bcc \
  --head ae0ac16cec6e2ba89c5814f3d1d936db90317582 \
  --json-output .validation/repeated-control.json
```

A repeat is another development trial, not an independent benchmark case. It
requires the configured inference service and may produce different model output.
Do not use a moving PR URL as the sole identity for an accuracy comparison.

Remaining requirements before a quality-qualified portfolio release:

1. Improve admission and impact context for large PRs: behavioral units should not
   lose their budget to import-only changes; report material omissions. Measure
   useful inspection and issue recall, not just response validity.
2. Validate reasoning with fresh positive/negative contrast cases and matched
   evidence. The 7B model still makes semantic mistakes. A stronger configured
   reviewer should be evaluated where local inference is insufficient.
3. Assemble the proposed real-PR pilot, pin and separate patch families, adjudicate
   defective/clean/uncertain labels, and seal held-out predictions. No real-PR
   precision, recall, false-MERGE rate, or calibrated confidence claim exists yet.
4. Add durable task/event recovery, cancellation/idempotency, incremental review,
   and finding/feedback lifecycle. Session persistence is not durable task recovery.
5. Qualify an isolated execution runner and reproducible release before executing
   arbitrary PR code, then measure latency, completion, resource use, and cost on
   that release revision. Author-reported PR tests are not harness evidence.

Current resume claims can describe the implemented evidence contracts, bounded
native inference, explicit partial outcomes, merge-safety scorer, 773-test local
suite, and hosted contract matrix. They must not imply demonstrated review accuracy
or production readiness.
