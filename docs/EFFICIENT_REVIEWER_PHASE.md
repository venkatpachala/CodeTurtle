# CodeTurtle efficient reviewer milestone

## Implementation and acceptance status

| Priority | What works | What the evidence still leaves open |
| --- | --- | --- |
| Large PR admission | Ranked change units, bounded source context, shared pinned impact lookup, explicit per-unit omissions | The 12-call LiteLLM trial inspected 11 of 100 eligible units. Coverage and speed improvements need a controlled baseline. |
| Reasoning evaluation | Native Ollama runs, sealed positive/repair pairs, independent Docker oracles, matched GPT reference answers | The latest synthetic transfer run missed one of two defects after tuning. The stronger model was a reference for the same questions, outside the runtime. |
| Real-PR pilot | 60 frozen inputs, family and exposure separation, online issue-reference import, resumable blind predictions and safety accounting | Published positives cover only part of the registry. Clean controls, semantic family audit and prior exposure remain open. |
| Durable runtime | SQLite job ledger, claims, leases, recovery, cancellation, idempotency, bundle checkpointing and finding events | Current scope is a local worker, an operator-supplied repository and a shared SQLite database. |
| Execution and release | Qualified Docker fixture profile, frozen reviewer and observed model metadata, test matrix | Release quality gates, representative performance, peak memory and monetary inference cost remain open. |

The first sealed 30-PR pilot produced zero verified findings and one MERGE
recommendation on an externally labeled defective PR. It gives us a
reproducible failure case.

## 1. How the reviewer spends its budget

The runtime converts each diff into change units and ranks source and test changes by
signals such as removed conditions, returns, effects and mutation. Declaration-only
changes receive lower priority. A bundle has bounded units, characters and steps,
and the run has a shared model-call budget. The trace keeps the selected units and
reasons for deferral. These priorities control where inference time goes. Actual
inspection requires a valid behavior assessment with evidence references.

The impact index reads exact HEAD blobs, scans changed paths first and reuses its
bounded lexical index across bundles. This can identify relevant definitions,
references and tests with a fixed file and character budget. Reference hits do
not establish caller reachability. Pinned BASE and HEAD source remain the
authority for citations and behavior checks.

The diff parser previously resolved duplicate basenames before checking exact
paths. In a repository with many files named `mod.rs`, a path could inherit another
file's hunks. Exact paths now take precedence and ambiguous aliases fail closed.
The parser also distinguishes hunk content from headers, including C++ increment
and decrement lines that begin with repeated plus or minus signs in a patch.
Earlier complex-PR inventory and inspection counts affected by path aliasing
cannot support a comparison.

The [frozen LiteLLM #53342 run](validation/efficient-reviewer-v1/runtime/direct-large.json)
on reviewer `8895b19` used the submitted BASE and HEAD commits recorded in its
target, 12 model calls, 24,579 reported input tokens and 3,416 output tokens.
It took 214.20 seconds, selected 53 of 100 eligible units, inspected 11, and
returned partial `COMMENT` with 16 unresolved records and zero product findings.
The earlier corrected run at `2727ce2` inspected 13 of 100 in 216.96 seconds.
These are individual development observations. [Original PR](https://github.com/BerriAI/litellm/pull/53342)

## 2. How the system separates observed behavior from intended behavior

For a narrow subset of pure Python functions, a bounded AST evaluator calculates
BASE and HEAD values on the same literal input. It imports and executes no target
code. If an operation is outside its supported subset or the result exceeds its
budget, it drops that example. It preserves Python types and chooses integer
inputs for both operands of ordered comparisons where applicable. Examples
include the source hashes, return operation and path.

A revision-neutral question asks the model what the explicit requirement calls
for. With integer-valued outputs, discovery asks for the expected integer without
exposing the two outcomes. A supplied number must match an observed value to
produce a proposal. The final verifier challenges the contract separately,
replays both source expressions and resolves citation text against the exact
snapshot. Recent results record this as a model-assisted verification on schema
2.4. Two calls to the same model can share a reasoning error.

| Experiment | Introduced-defect cases with a finding | Repairs with a finding | Scope |
| --- | ---: | ---: | --- |
| UTF-8 and pagination, latest rerun | 2/2 | 0/2 | Two families used during development |
| Expiry and signed delta, first frozen run | 0/2 | 0/2 | Two new families, four directional cases |
| Integer input and relation fix | 1/2 | 1/2 | Detected expiry; signed delta missed and repair wrongly flagged |
| Direct integer discovery | 1/2 | 0/2 | Retained expiry; signed delta still unresolved at verification |

Trusted BASE/HEAD assertions in Docker confirmed both directions of all four
families. The last native runs used 8 calls and 31.91 s on the initial families
and 7 calls and 28.56 s on the transfer families. The reported completion-token
totals were 574 and 474. These are timings for four cases per run.

`gpt-6-astra` answered the same discovery packages and schemas through Codex CLI.
It recognized that the first expiry example used a boolean where the requirement
called for integer ticks, and computed the signed increase correctly. The original
UTF-8 and pagination questions were also answered correctly. Reversed cases
often share a question, leaving four distinct questions across the two suites.
The production/default reviewer in these experiments was `qwen2.5-coder:7b`.
The [captured questions, predictions and seals](validation/efficient-reviewer-v1/experiments)
and [matched answers](validation/efficient-reviewer-v1/reference.json) preserve disagreements.

## 3. How the benchmark avoids mixing predictions and answers

The frozen registry stores PR URLs, BASE, HEAD, merge bases, patch hashes,
and split membership. Transitive exact-patch and source-URL grouping occurs
before splitting, and known exposure propagates within a family. The exact
family audit recovered the same input digest with no known crossing among
20 development, 10 validation and 30 test PRs. Semantic near-duplicates
and prior exposure to this public data still require assessment.
[Registry and annotation protocol](../benchmark/datasets/real_pilot_v1/ADJUDICATION.md)

The online import linked 40 PRs to 141 published issue references. The first
pass matched both frozen trees to archived reviews for all 40. The follow-up
resolved 39 and recorded a request failure on the remaining development case.
The first pass gives 38 externally labeled defective PRs using functional
categories bug, concurrency, data, API and security. Pure documentation,
style, performance and other categories remain available in the source index.
The 20 controls have no matching published reference. An exact-revision
approval alone does not exhaustively review a PR. [Published references](https://github.com/withmartian/code-review-benchmark/tree/23a35d0d64f7de5a68e5679da08414e0edacea9b/offline/golden_comments)

The blind command reads the registry and patches without reading annotations.
It obtains changed-path source on demand through GitHub commit, tree and blob
objects, checks blob identity, and checkpoints each result by PR and profile.
The test trial uses one bundle and two agent steps per case in this profile.
Replaying after an interruption requires the same reviewer revision, model
digest and configuration. Seals require one attempt for every test input,
including explicit failed or no-verdict attempts. Source scope is narrower
than a full local checkout.

### Sealed test-split result

| Measure | Observed value |
| --- | --- |
| Attempts | 30/30 sealed on `6ad326e` |
| Analysis health | 10 completed, 20 partial |
| Decisions | 28 COMMENT, 2 MERGE, 0 no verdict |
| Inspected scope | 84 of 392 eligible units |
| False-MERGE among defective PRs | 1 of 19, or 5.3% |
| Defective among MERGE recommendations | 1 of 1 labeled MERGE recommendations. The other MERGE was unlabeled |
| Reference issue matches | 0 matches for 67 published issue references, with zero product findings |
| Model work | 51 budgeted calls, 117,872 reported input tokens and 13,338 output tokens |
| GPU resume latency | 21 cases, p50 39.0 s and p95 63.2 s |
| GPU resume resources | 4,104,734,637 bytes sampled resident model VRAM, 99,896 KiB max WSL reviewer-child RSS |

The other 11 cases have no accepted functional defect or clean label. The
nominal Wilson 95% interval on 1/19 is 0.9%–24.6%. It assumes independence and
representative sampling, which remain unestablished for this purposive split.
With zero emitted findings, issue precision is undefined. The reference-match
count concerns the published issue list and this particular profile.

The run resumed twice from case checkpoints. The original six cases have no
per-case hardware sampling. Three cases completed on CPU during service
recovery. The last 21 used CUDA with the same endpoint and model digest. GPU
latency figures use the CUDA cohort only and include GitHub source fetches.
Memory figures cover reported resident model allocation and the one WSL
reviewer child. Monetary cost is unmeasured.
[Sealed report](validation/efficient-reviewer-v1/real-pilot-test/report.json)

`P(MERGE | defective)` counts merges among the defect-labeled PRs.
`P(defective | MERGE)` counts defects among labeled recommendations to merge.
The second metric is undefined when the system recommends no merges. For
portfolio reporting, a low first number is meaningful only alongside the
decision mix, inspection, clean merge coverage and uncertainty. Public
benchmark exposure and partial labels limit generalization even when a
numerator and denominator can be reported.

The observed false MERGE was [Cal.com #14943](https://github.com/calcom/cal.com/pull/14943).
The older reviewer counted all three units as inspected and treated the
edited database updates and deletion criteria as consistent. The follow-up
prioritizes visible storage mutations, including edits inside call arguments.
Even with full inspection and no finding, those changes now require human
review. A verified blocking finding can still request changes. This lexical
guard covers recognizable persistence APIs. Broader stateful changes and
defect detection still require evaluation.
Replaying policy against the original artifact changes MERGE to COMMENT.
A fresh native run on the same pinned trees at `461daa8` independently
returned COMMENT with `persistence_change_requires_review` and zero findings
in 40.28 seconds. This known-case retest does not change the sealed pilot
score. [Regression evidence](validation/efficient-reviewer-v1/persistence-regression/check.json)

## 4. What makes the runtime durable

A submitted job captures the repository, pinned revisions, relevant review
options and an idempotency key. SQLite transactions and leases let a worker
claim it while preventing a stale worker from publishing a finishing update.
A crashed worker's lease expires and eligible work can be reclaimed. The
supervisor maintains the heartbeat, can terminate its child on cancellation
or timeout, and recovers validated artifacts written before a crash. The
default running limit is one for a local GPU.

Bounded discovery checkpoints are keyed by exact inputs, reviewer code and
configuration. A cache hit reuses only a healthy discovery result, and final
verification still runs. A previous canonical result can also serve as an
incremental baseline when its HEAD equals the current BASE. Unresolved prior
findings carry forward. A missing finding is recorded as needing recheck,
and operator feedback requires audit evidence. This keeps a changed code
location or omission from silently closing a real issue.
[CLI recovery and cancellation smoke](validation/efficient-reviewer-v1/runtime/job-cli-qualification.json)

## 5. What execution and release qualification established

The explicit `sandbox-check` command stages regular blobs from pinned revisions
into a digest-pinned Docker image and applies the same command on BASE and HEAD.
The Linux container has a read-only root and source mount, no network, explicit
resource ceilings and a non-root user. The qualification probe verified these
controls, absence of the host canary and Docker socket, differential pass/fail,
deadline, output cap, OOM detection and cleanup. The normal review runtime
blocks legacy host-side test and install flags. The qualified profile covers
small Python probe workloads. Building arbitrary PRs and installing dependency
sets needs separate runner and workload qualification.
[Execution qualification](validation/efficient-reviewer-v1/runtime/isolation-qualification.json)

The full local suite after the persistence fix passed **833 tests** with
five Docker integration checks skipped in that run. The separate Docker
qualification covered the executable fixtures. The hosted four-job
Windows/Linux and Python 3.11/3.12 matrix covers selected contracts.
[Test record](validation/efficient-reviewer-v1/runtime/test-qualification.json)

The release manifest freezes the clean reviewer commit, dependencies, scorer
hash, configured model and observed Ollama digest. Two wheel builds at pilot
revision `6ad326e` using a fixed `SOURCE_DATE_EPOCH` were byte-identical.
The installed wheel passed help-command smoke tests outside the repository,
with runtime dependencies supplied by the existing environment.
[Wheel build record](validation/efficient-reviewer-v1/runtime/wheel-qualification.json)

During one four-case transfer
run, peak reviewer-child RSS was 78,872 KiB and sampled Ollama resident model
VRAM reached 4,104,734,637 bytes. That excludes transient and shared GPU overhead.
The model digest matched before and after. Monetary cost was left unset because
local electricity and system costs were outside the measurements.

## Reproduce from WSL

```bash
.venv/bin/python -m cli.main review URL --github-auth gh --dry-run --json-output review.json
.venv/bin/python -m cli.main jobs submit --repo /path/to/repo --base BASE --head HEAD
.venv/bin/python -m cli.main jobs work --max-jobs 1
.venv/bin/python -m benchmark.native_contrasts \
  --corpus benchmark/datasets/contrast_transfer_v1 --output trial-new
.venv/bin/python -m benchmark.blind_pilot benchmark/datasets/real_pilot_v1 \
  --split test --output pilot-new
.venv/bin/python -m benchmark.pilot benchmark/datasets/real_pilot_v1 \
  --predictions pilot-new/predictions.json --annotations path/to/annotations.json
```

Use a clean reviewer checkout for prediction. Keep labels separate and score
after sealing. For isolation qualification, use
`python -m benchmark.qualify_runtime --help` to set the Docker executable,
staging root, image digest and output.
