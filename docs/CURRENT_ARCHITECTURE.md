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
5. Build change units and bounded implementation/test bundles.
6. Run deterministic structural rules and model hypothesis discovery.
7. Retrieve hunks, bounded HEAD source, and caller/test/graph context.
8. Construct proof, with at most one repair pass inside the model-call budget.
9. Ground, position, reflect, and independently verify candidates.
10. Build canonical findings, evidence-backed process coverage, health, and unresolved hypotheses.
11. Evaluate a pure product policy once.
12. Render terminal, JSON, benchmark product output, and publication preview.
13. If explicitly requested, deliver one SHA-bound GitHub review containing summary and inlines.

## Canonical result

`ReviewResult.to_dict()` is schema version `2.0`. It includes target, health,
inspection, findings, product findings, execution, trace, model/config provenance,
policy reasons, and bounded-work telemetry. `findings` is diagnostic; the
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
and subprocesses across Windows/Linux and Python 3.11/3.12. Its live execution on
GitHub still requires pushing this implementation.
