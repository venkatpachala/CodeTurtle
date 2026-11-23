# Current architecture: 0.5.0a1 preview

The default path is `cli.commands.review.ReviewPipeline` followed by the linear
`core.runtime.review_runtime.ReviewRuntime`. It does not invoke LangGraph.
The legacy runtime remains an explicit compatibility option; its outputs do
not have the v2 production contract guarantees.

## Runtime and boundaries

1. Select configured, GitHub CLI keyring, or anonymous authentication.
2. Fetch PR identity and exact BASE/HEAD SHAs. Frozen-input assertions reject drift.
3. Hold an OS-backed repository lease across checkout, analysis, and publication.
4. Check out HEAD and verify the resulting Git revision. Git authentication is
   passed through subprocess environment headers, not clone URLs.
5. Build change units; prepare pinned comparison history with bounded fetches;
   create bounded implementation/test bundles.
6. Run deterministic structural rules and model hypothesis discovery.
7. Retrieve sealed hunks, pinned HEAD source, and bounded snapshot lexical context.
   Normal PR risk reads also use pinned Git objects; no checkout fallback follows
   CLI snapshot-preparation failure.
8. Investigate up to two hypotheses per semantic bundle with separate discovery,
   investigation and verification capacity under the shared model-call ceiling.
   The backend generates immutable source-span choices for BASE and HEAD.
   A bounded repair can retry a malformed response against the same evidence.
   Remaining failures preserve partial progress and cannot imply approval.
9. Ground, position, reflect, and independently verify candidates.
10. Build canonical findings, evidence-backed process coverage, health, and unresolved hypotheses.
11. Evaluate a pure product policy once.
12. Render terminal, JSON, benchmark product output, and publication preview.
13. If explicitly requested, deliver one SHA-bound GitHub review containing summary and inlines.

## Canonical result

`ReviewResult.to_dict()` emits schema version `2.4`. It includes target, health,
inspection, findings, product findings, execution, trace, model/config provenance,
policy reasons, and bounded-work telemetry. The additive requirement contracts
record intent sources, requirements, assessments, investigations, and evidence.
`ReviewResult.from_dict()` accepts a canonical result or its CLI envelope and
upgrades stored `2.0` through `2.3` results to `2.4`. `findings` is diagnostic; the
`product_findings` projection contains verified defects. No empty-list fallback
reconstructs v4 findings from legacy comments.

CLI JSON retains historical benchmark keys and nests the entire canonical object
under `result`. Top-level `findings` and `review_comments` contain product output;
`diagnostic_findings` preserves survivors for investigation. Publishing status
and the exact preview are separate fields. JSON writes are atomic and reject NaN.

## Coverage

Eligible process units currently have source/test classifications. Packed units
entered scheduled bundles. Inspected units require model-recorded behavioral
delta, hypothesis outcome, and a valid unit evidence reference from a healthy run.
Missing, truncated, or invalid assessments do not count as inspected. Zero eligible
units produce a null ratio. These records establish process coverage, not semantic
correctness or proof that all bugs were considered.

Requirement coverage counts verified, violated, unverified, and unassessed
requirements. A missing assessment counts as unassessed. Reasoned not-applicable
requirements are excluded from the denominator. Its ratio is assessed divided by
applicable requirements and is null when none apply.
Conclusive requirement assessments cite directional evidence for the reviewed
HEAD. BASE evidence can provide historical context. The existing verdict
continues to use source-unit inspection. Findings linked to the new
investigation records require a confirmed investigation and supporting HEAD
evidence to enter product output. Stored v2.0 findings retain their existing
verification status during migration.

Intent/evidence classes are owned by `core/domain/review_contracts.py`; the previous
`core/review/requirements.py` import path re-exports those same classes. Legacy
`*_ids` record inputs remain accepted; canonical domain records serialize `*_refs`.
An explicitly selected `--requirements` JSON file scopes acceptance criteria to paths.
It informs discovery and proof construction. A separate source-level assessment can
link verified defects to violated requirements in GitHub PR mode. Local snapshot
mode additionally supports requirement-first planning, structured investigation,
fresh verification, and exact source citations. A requirement-driven candidate
still passes normal finding gates. Bounded satisfaction support is scoped and
does not establish complete source inspection or universal correctness.

Typed `source_observations` record tool-produced revision-bound excerpts. Evidence
can reference them, and the canonical result validates snapshot/revision identity
and excerpt digests. Structured model decisions and per-requirement outcomes remain
inspectable in provenance. See REQUIREMENT_FIRST_PHASE.md for the current protocol.

Final model verification now uses structured source-bound decisions and records
both support and counterevidence in `finding_verifications`. Graph keyword matches
and related test names are hints rather than automatic refutations on this route.
Malformed output, unavailable context, and exhausted budgets remain unresolved.
PR source capture distinguishes the target tip (`base_sha`) from the historical
comparison merge-base (`comparison_base_sha`). Existing deterministic verification
routes remain separate. See SOURCE_FINDING_VERIFICATION.md for the contract,
limits, tests, and paired verifier experiment.

Proof and final-finding requests now send JSON schemas through the provider.
Ollama context defaults explicitly to 8,192 tokens. Generation records include
schema digest, requested limits, finish reason, and output truncation. Provider
success and schema validity remain separate from grounded semantic correctness.
See [the proof reliability phase](PROOF_RELIABILITY_PHASE.md) for the saved native
PR run and the unresolved fixed-candidate final-gate checks.

Normal PR investigations now share snapshot-backed source/search tools and Python
AST context. Bounded function observations declare their scope, absolute lines,
and unresolved lexical dependencies. A narrow `python-none-len-v1` source rule
can verify an already proposed direct None/len candidate without a final model
request. Records distinguish model verification from source-rule verification;
the latter is reproduced against recorded observations during contract validation.
See [snapshot context and source verification](SNAPSHOT_CONTEXT_PHASE.md).

## Local committed snapshots

`codeturtle review-local --base REF [--head REF]` compares exact committed trees
without checkout, repository execution, or GitHub publication. Dirty and untracked
files are excluded. `GitSnapshotProvider` reads regular Git blobs bound to sealed
BASE/HEAD, diff, and supplied configuration hashes. Snapshot tools use bounded
lexical retrieval and never fall back to mutable checkout reads. Checkout-based
rules and graph evidence are not used on this path.

For Python files, bounded AST comparison supplies changed symbols, signatures,
and module statements. Parse failures and omissions remain explicit gaps. This
is structural context, not resolved dataflow or behavioral proof. `--static-only`
skips model requests and reservations and preserves incomplete inspection.
Local `--requirement-strategy` selects investigate (default), link, or off;
`--max-requirements` bounds task admission. See REQUIREMENT_FIRST_PHASE.md.

## Policy

Failed/skipped analysis has no code verdict. A verified blocking defect requests
changes even if the remaining analysis is partial. Otherwise partial analysis,
incomplete inspection, material unresolved hypotheses, or unattributed failing
execution produces COMMENT. Complete inspected analysis without findings can
recommend MERGE. Medium-and-above verified defects are blocking under the preview's
default policy; blocking is stored separately from severity.

MERGE is a recommendation. GitHub receives COMMENT unless `--approve` is explicitly
requested and eligibility permits it. CodeTurtle never calls a merge API.

## Delivery

The pure publication plan validates repository/PR identity, reviewed diff hash,
HEAD SHA, decision, and inline locations. Every verified finding appears in the
summary, including findings that cannot be anchored inline. Publishing refreshes
PR BASE/HEAD before submitting. Duplicate lookup requires the same publisher,
commit, and deterministic plan marker. After an ambiguous failure, existing
reviews are reconciled; there is no blind mutation retry.

An OS repository lease prevents concurrent local checkouts from overwriting each
other. Actions also use PR-scoped concurrency. This is not a distributed exactly-once
guarantee across machines.

## Budgets and observability

Model work is sequential. Defaults cap shared model calls at 12, cumulative prompt
characters at 120,000, and wall time between calls at 300 seconds. Provider HTTP
requests have a 120-second timeout. Wall time can exceed the between-call budget by
an in-flight request. Tool retrieval has independent bounded scans and text limits.
Recorded usage is actual provider token telemetry; character estimates are labeled
as estimates. Price-based costs are not fabricated.

## GitHub Actions

Review workflows install trusted base-repository tooling or an audited commit SHA.
They do not check out or install the analyzed PR. Fork automation is intentionally
excluded. Publishing is explicit through manual dispatch. Third-party Actions are
pinned by commit. Repository test execution is rejected in GitHub Actions.

The contract CI runs actual deterministic components, filesystem operations, Git,
subprocesses, and local HTTP gateway contracts across Windows/Linux and Python
3.11/3.12. Recorded hosted runs passed the four-platform matrix; each report is
evidence for its specific commit. See FINDING_VERIFIER_VALIDATION.md and
PROJECT_STATUS.md for the current milestone and remaining work.
