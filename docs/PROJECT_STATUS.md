# CodeTurtle project status and portfolio evidence

Status date: 2026-11-21. CodeTurtle is a CLI-first, local-first code-review engine
with a modular Python runtime. It is a preview, not a completed CodeTurtle 2.0
release or a demonstrated high-recall reviewer. The default runtime is sequential
and does not use LangGraph. Optional integrations do not establish broad quality.

## Implemented system

| Layer | Current implementation | Practical boundary |
| --- | --- | --- |
| Input | GitHub PR intake; direct local committed comparisons; revision identity | The entire PR path has not migrated to immutable snapshot tools |
| Planning | Change units, bounded source/test bundles, explicit scoped requirements | Packing is not inspection; omission remains visible |
| Investigation | Structural rules, bounded hypothesis discovery, typed proof batches and shared repair limits | Model reasoning and broad-language accuracy remain unqualified |
| Requirement investigation | Local requirement-first proposal and fresh challenge | GitHub mode currently supplies requirements and links verified findings |
| Retrieval | Diff hunks, source lookup, Python AST change context, optional graph tools | No comprehensive impact/dataflow guarantee; graph can be unavailable |
| Verification | Structured decisions, exact citations, HEAD support/counterevidence, one repair | Valid source grounding does not establish semantic truth |
| Result | Canonical schema 2.3, claim identities, evidence links, health and unresolved records | Historical schemas remain readable; inspection describes process |
| Policy | Deterministic MERGE/COMMENT/REQUEST_CHANGES or no verdict | MERGE is a recommendation, not a merge operation or correctness proof |
| Delivery | Dry-run preview and explicitly requested SHA-bound grouped GitHub review | Cross-machine exactly-once delivery is not guaranteed |
| Persistence | Local session/memory/repository utilities and JSON artifacts | No complete durable review-task recovery/event ledger |
| Evaluation | Frozen input helpers, separate labels, sealed predictions, scorers, paired analysis | Expanded real-PR benchmark and explicit false-MERGE uncertainty are unfinished |

## Current system flow

1. Load configuration, selected provider, GitHub authentication, and optional user requirements.
2. Fetch PR metadata and BASE/HEAD identities; apply configured skip/ignore policy.
3. Acquire a repository lease, prepare the checkout, and verify the reviewed HEAD.
4. Build the diff and change units; prepare pinned historical source with bounded fetches; record missing context and scope omissions.
5. Pack bounded bundles and run structural rules plus model hypothesis/proof stages.
6. For local snapshot review with supplied requirements, additionally investigate each admitted requirement and challenge proposals.
7. Apply proof, location, and reflection gates to candidates.
8. Apply deterministic verification where its narrow contract holds; otherwise request and validate a source-bound final model decision.
9. Preserve supported, refuted, unresolved, malformed, unavailable, and exhausted outcomes with their evidence and attempts.
10. Assemble canonical findings, inspection accounting, execution evidence, and health.
11. Apply deterministic product policy and render terminal/JSON output.
12. Publish only when explicitly requested; refresh target identity before submission.

The result separates execution health from recommendation. A verified blocking
defect can request changes despite partial remaining analysis. Partial work,
unresolved hypotheses, or insufficient inspection normally yield COMMENT.
Failed/skipped analysis has no code verdict. Empty findings alone do not establish
approval eligibility. Repository execution is disabled by default.

## Connection and gateway validation

WSL's normal gateway was initially pointed at an unreachable `localhost:11434`.
The already-running Windows service was reachable through the WSL default-gateway
address. The local WSL user configuration now selects that verified endpoint and
the installed `qwen2.5-coder:7b` model. Configuration is machine-local and is not
committed as a portable endpoint. The host address may need refreshing after a
network restart.

The connection investigation also found a real gateway defect: `retries=0`
executed zero provider calls. The fix makes zero issue one request without retry,
preserves positive legacy attempt budgets, rejects negative budgets, and exposes
exhaustion as a runtime error. Five tests exercise the real gateway/provider/SDK
over a local HTTP server, including requests and reported token usage. The server
is a controlled test service; it does not measure LLM quality.

A real normal-gateway request returned `CONNECTED` with provider token telemetry.
That establishes inference connectivity, not review accuracy. See cli.md for the
WSL setup and validation artifacts for measured results.

The normal CLI also completed a dry-run on the previously used public development
case `ai-code-review-evaluation/discourse-graphite#1`: three changed files, four
recorded inspected units, eight model calls, and one product finding. It returned
REQUEST_CHANGES with partial health and 17 unresolved entries. The reported issue
concerned percentage geometry on the animated GIF resize path and passed an
existing static contract route. The new source-bound final model verifier was
not exercised: its snapshot was unavailable in the shallow checkout. Graph context
was also unavailable. No GitHub review was posted.

This is an end-to-end integration smoke, not independent adjudication of a true
positive or a quality improvement. Its 222.58-second wall time is one observation,
not a latency percentile. Recorded process inspection of 4/4 is compatible with
partial health and unresolved analysis. See the [connection validation record](validation/2026-11-21-normal-gateway.json)
for target identities, usage, CI evidence, and limitations.

## Evidence we have

- Full local suite: 697 tests passed after proof-protocol reliability work,
  extending the previous 663-test gateway milestone. See
  [the implementation and validation report](PROOF_RELIABILITY_PHASE.md).
- Four stored offline evaluation snapshots passed in the previous validation.
- Hosted contract matrices have passed Windows/Linux and Python 3.11/3.12 for
  their recorded commits. New changes must be checked on their own revision.
- Two sealed verifier experiments contain 12 reviews of four distinct synthetic
  development cases, with 53 actual model requests. They show no detection gain.
- The local model still fails to publish a known removed-guard defect. Malformed
  and contradictory structured decisions remain unresolved and inspectable.
- Existing real-PR development diagnostics and source adjudication files are not
  a completed independently labeled held-out quality benchmark.
- The original LiteLLM PR now completes its normal CLI protocol: three requests,
  two valid proof batches, COMMENT/partial, seven unresolved records, zero product
  findings, and no publication. A fixed-candidate final-gate replay still misses
  the removed-guard defect; the preserved-guard control also remains unresolved.

The benchmark adapter's Windows `/api/generate` runs and the normal gateway's
native `/api/chat` smoke are different protocols/profiles. Do not combine their
latencies or outcomes into a controlled quality comparison.

## Remaining implementation, in dependency order

### 1. Finish the normal PR input and model contracts

Bounded historical Git preparation and explicit model context/options are now
implemented. Finish the shared immutable PR investigation adapter.
Replace whole-file-first truncation with scoped evidence capture whose completeness
is honest. Current final verification admits six paths, 120 lines per file, and
10,000 shared source characters; this can leave ordinary large files unresolved.

### 2. Isolate and improve verification reliability

Freeze a candidate and its observations before comparing verifier variants.
Measure schema validity, citation validity, semantic decision quality, repairs,
abstention, requests, tokens, and latency separately. Provider-constrained output
is implemented and live-tested; it has not established semantic improvement.
Test backend-resolved citation text without silently changing a wrong verdict. Use a
bounded stronger-model comparison if needed; no improvement is presumed.

### 3. Implement explicit benchmark truth and decision metrics

Represent defective, reviewed-clean, and uncertain cases explicitly. Missing
reference comments must not imply clean code. Add both buggy-PR MERGE rate and
unsafe fraction among MERGE recommendations, raw denominators, uncertainty, clean
recommendation coverage, finding quality, and operational completion. Preserve
failed and ambiguous attempts. A system that abstains on everything is not useful.

### 4. Assemble and adjudicate the real-PR pilot

The proposed pilot is 60 unique underlying cases: 20 development, 10 validation,
and 30 held-out. Proposed composition is 40 defect-bearing and 20 reviewed-clean
controls. Source candidates come from the existing public replica pool and
additional public controls; exact membership and labels are not assembled yet.
The proposal is not an implemented dataset or a measured result.

Keep patch families together, audit prior exposure, pin source identities, and
seal predictions before scoring. Venkat is the currently available human labeler;
no independent reviewer has been secured. Without one, describe the work as an
author-adjudicated pilot. Report small denominators and wide intervals explicitly.

### 5. Complete durable runtime and developer lifecycle

Add durable review-task state and event recording, interrupted-run recovery,
idempotency, bounded scheduling/cancellation, and dependency-aware incremental
re-review. Add finding resolution and feedback tracking. These extend existing
session/repository persistence rather than treating it as resumable review state.

### 6. Qualify a reproducible release

Freeze reviewer/model/configuration/scorer identities, run matched baselines and
fresh held-out evaluation, and test failure/recovery scenarios. Complete an
isolated runner before arbitrary untrusted BASE/HEAD execution. Verify packaging
and delivery lifecycle on the release revision, document limits, and begin with
shadow/dry-run use. Approval eligibility requires quality evidence beyond tests.

## Portfolio and resume claims

Current defensible claims concern architecture and demonstrated engineering:
typed evidence contracts, pinned source identity, bounded model orchestration,
explicit incomplete outcomes, real HTTP gateway regression tests, and recorded
cross-platform CI. State the measured test scope and revision.
The normal CLI has now exercised GitHub intake, checkout, model calls, policy,
terminal/JSON rendering, and publication preview on a real development PR. Its
result remained partial. Dollar cost and model confidence calibration are not
measured; a displayed confidence score is not benchmark accuracy.

Do not claim real-PR precision/recall, a low false-MERGE rate, a model accuracy
gain, robust arbitrary-PR coverage, production readiness, or a completed 2.0
roadmap. The goal is a reproducible report with case counts, adjudication quality,
confidence intervals, latency/cost scope, and disclosed failure modes that can
support those claims when the evidence exists.
