# CodeTurtle Phase II: first frozen-reviewer validation

This is diagnostic evidence, **not a release benchmark or competitor comparison**.
The reviewer implementation was frozen at commit
`849ca1de93aee4ca01b5c540be121ccf2706344d`; the run manifests record
`reviewer_dirty=false`. The model was `qwen2.5-coder:7b` on local Ollama,
with v4 runtime, four-bundle and four-step caps. Reviews were dry-run and
posted nothing to GitHub. Graphify was disabled in the review logs.

The validation split was selected by PR URL before inspecting gold comments:

| PR | Model output | Elapsed |
| --- | --- | ---: |
| `ai-code-review-evaluation/discourse-graphite#2` | 0 findings, MERGE | 246.98 s |
| `ai-code-review-evaluation/keycloak-greptile#1` | 0 findings, MERGE | 372.72 s |
| `ai-code-review-evaluation/sentry-greptile#2` | 0 findings, MERGE | 392.42 s |

Post-run provenance audit found that `keycloak-greptile#1` replicates
`keycloak/keycloak#41249`, which has a historical CodeTurtle output in
`benchmark/results/keycloak_keycloak_41249.json` (September 16). Treat the
Keycloak case as **historically exposed**, not genuinely unseen. Its result
remains in this sealed three-PR pilot; it is not silently replaced. A separate
predeclared validation extension uses `discourse-graphite#3` to restore a
three-PR previously unreviewed cohort. Its gold was not opened before its
prediction run.

The original Keycloak attempt failed during Git checkout because of Windows
path length. A process-scoped `core.longpaths=true` retry filled only that
missing prediction. Its checkout HEAD matched the PR SHA in the review log.
The original failure remains recorded as an infrastructure incident. The
median successful review latency was 372.72 s; nearest-rank p95 was 392.42 s.

## Previously unreviewed cohort after provenance audit

The two original pilot cases without local predecessor artifacts were
`discourse-graphite#2` and `sentry-greptile#2`. The predeclared replacement,
`discourse-graphite#3`, ran at the same frozen reviewer commit and model,
took **167.54 s**, emitted **0 findings**, and returned
`COMMENT / review_inconclusive` because one of four bundle-agent runs had
invalid JSON. Its gold was opened only after its prediction was sealed.

For the replacement PR, one regex-boundary issue was confirmed (the source
label's specific `evil.example.com` example was wrong; the actual bypass is a
suffix such as `example.com.attacker.tld`). One side-effect claim was rejected
because the behavior is intentional and asserted by tests. A case-sensitivity
claim remains ambiguous because the code deliberately preserves email
local-part case and the required block-policy semantics were not established.

Thus the **three-case previously unreviewed cohort** has **five confirmed
known issues, zero detected**. The audited misses are three
`HYPOTHESIS_MISS` and two `PROOF_MISS`. This is issue-detection evidence,
not a valid precision/F1 estimate: none of the three reviews emitted a
finding, two cases have unresolved labels, and the corpus has no clean PRs.
The historical Keycloak case is excluded from this cohort. The two run
reports remain separate so no prediction is silently replaced or selected
after looking at its quality.

## Labels and measured outcome

Eight upstream gold comments were inspected after predictions were sealed.
Five were confirmed from changed source and relevant contracts; one was
rejected as a style-only typo whose controller/template names agree; two
remain ambiguous because their required product or permission-path behavior
was not established. The confirmed known-issue detection rate was **0/5**.

Only one PR has all labels adjudicated, so confirmed-label PR-level metrics
cover that PR alone: **TP 0, FP 0, FN 1, recall 0%**. Precision and F1 are
**N/A**, not 0%, because no findings were emitted. Source-label-only metrics
over all three PRs are provisional: **TP 0, FP 0, FN 8**. All three decisions
were MERGE despite known issues. There are **no clean PRs** in the source
50-PR benchmark, so this experiment says nothing about clean-PR false-positive
rate. A zero FP count with zero predictions is not evidence of precision.

The release gate fails due to insufficient sample, no clean controls, missed
blocking issues, incorrect decisions, p95 latency above 300 seconds, an
infrastructure incident, and two
unresolved labels. This result should not be used as a headline quality claim.

## Audited failure attribution for confirmed misses

| PR and gold | Stage | Evidence |
| --- | --- | --- |
| Discourse G-001 (`TopicUser.find_by` nil dereference) | HYPOTHESIS_MISS | Related bundle generated only a generic unsubscribe edge-case concern; no candidate. |
| Keycloak G-001 (zero-argument passkey method call) | HYPOTHESIS_MISS | Hypotheses discussed passkey behavior, not the call/declaration signature mismatch. |
| Sentry G-001 (optimized negative QuerySet slice) | PROOF_MISS | Negative-offset hypothesis and paginator hunk retrieval; healthy bundle produced zero candidates. |
| Sentry G-002 (previous-page negative QuerySet slice) | PROOF_MISS | Same retrieved paginator contract, no constructed candidate. |
| Sentry G-003 (`floor`/`ceil` on datetime) | HYPOTHESIS_MISS | No recorded hypothesis identified the datetime/numeric type mismatch. |

This is a tiny, deliberately frozen sample. The observed next engineering
target is **specific hypothesis discovery and proof construction**, not a
new graph/CFG subsystem by default. Do not retune against these PRs and then
call them unseen again; they are now validation examples for subsequent
comparisons. Before a release claim, resolve the two ambiguous labels, add
real adjudicated clean controls, and run a larger held-out set.

The source adjudications and issue-level rationales are in
`benchmark/adjudications/validation_v1.json` and
`benchmark/adjudications/validation_v1_failures.json`. Local run artifacts
(`validation_report.md`, `aggregate.json`, per-PR predictions and logs) are
under `benchmark/runs/validation_v1_frozen_849ca1d/`; that directory is
intentionally Git-ignored. Dataset SHA-256:
`16815a81e492849d6ba97466ccf9878c277ed52c00a8e7087fe5a1d317f1b577`.
