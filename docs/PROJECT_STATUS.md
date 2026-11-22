# CodeTurtle project status and portfolio evidence

Status date: 2026-11-23. CodeTurtle is a local-first review CLI and worker with
a modular Python runtime. Use it for dry-run review and inspection of the
evidence trace. The available quality measurements describe specific profiles
and datasets.

## Implemented system

| Layer | Current behavior | Proven scope |
| --- | --- | --- |
| Input | GitHub PRs and committed local snapshots, exact BASE/HEAD and pinned source | Bounded Git preparation and source retrieval |
| Planning | Ranked change units and bounded model bundles with deferred-unit records | Behavioral priority, per-unit inspection accounting, shared lexical impact |
| Investigation | Structural rules, scoped requirements, model discovery and proof | Native inference, explicit partial and unresolved outcomes |
| Verification | Exact citations, small source rules and restricted pure-expression replay with a separate contract challenge | Schema 2.4 with backward reads, scope and input checks |
| Policy | MERGE, COMMENT, REQUEST_CHANGES or no verdict | Deterministic recommendation with reasons and review health |
| Delivery | Dry-run output and explicitly requested SHA-bound GitHub review | Target freshness checked before publication |
| Operations | Durable SQLite jobs, leases, cancellation, retry, exact-input bundle checkpoints, incremental findings | Local workers, one running review by default |
| Execution | Explicit digest-pinned Docker BASE/HEAD checks | Local controlled Python fixture qualification |
| Evaluation | Frozen inputs, external issue references, blind predictions, both false-MERGE denominators, Wilson intervals | Purposive public pilot with partial labels and an exposure audit pending |

## Runtime flow

1. Load the provider, model and limits, and pin the exact PR or local snapshots.
2. Parse per-file hunks and build a change-unit inventory.
3. Prioritize behavioral changes, pack bounded bundles and attach pinned context.
4. Run structural rules, model discovery and any enabled requirement investigation.
5. Validate candidate paths, trigger, BASE/HEAD attribution and citations.
6. Preserve completed, partial, unresolved and unavailable analysis evidence.
7. Apply deterministic policy and produce canonical findings, inspection data and traces.
8. Publish only on request after confirming the live target revision.

A verified blocker can request changes even when other scope remains partial.
Uninspected code and unresolved hypotheses can lead to COMMENT. Failed analysis
has no code verdict. Approval eligibility requires more than an empty findings list.

## Evidence and remaining work

The [efficient reviewer report](EFFICIENT_REVIEWER_PHASE.md) records the five
priorities, learning notes, sealed experiments, source-linked labels, resources,
and reproduction commands. Key outcomes include a local Docker qualification
and single-PR LiteLLM measurements. The latest LiteLLM run inspected 11 of 100
eligible units within 12 model calls and returned partial COMMENT. Earlier
large-PR runs before the exact-path fix have unreliable inventory counts.

The two tuned synthetic development families both produced their expected
regression findings and neither repair produced a finding. First-pass transfer
to two new families missed both regressions. After debugging, one of those
regressions still remained unresolved. The archived stronger-model answers
diagnose gaps on matched questions.

The frozen real-PR registry includes 60 inputs. Published issue references
matched both trees on 40. Under the functional category policy, 38 have external
defect labels. The other controls and near-duplicate or prior-exposure checks
still require adjudication. Report publicly sourced pilot statistics with their
exact denominators and scope. A reproducible code/model freeze and passing
contract tests establish engineering behavior. Broader coverage, issue matching,
clean-PR adjudication and repeated latency and resource measurement remain the
path to a qualified reviewer release.

## Portfolio framing

Describe the backend you built and the checks it passes. Good evidence includes
pinned source and typed citations, bounded model routing, SQLite recovery and
cancellation, isolated revision execution, and separate frozen benchmark truth
and predictions. Include the test revision and dataset size with any metric.
The offline local model's reported token counts support reproducibility. Local
energy, hardware depreciation and monetary cost have no measurement here.

Earlier milestones remain recorded in the [semantic review report](SEMANTIC_REVIEW_PHASE.md),
[snapshot context report](SNAPSHOT_CONTEXT_PHASE.md) and
[proof reliability report](PROOF_RELIABILITY_PHASE.md).
