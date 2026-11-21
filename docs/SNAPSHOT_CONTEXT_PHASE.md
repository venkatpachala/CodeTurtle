# PR snapshot investigation and scoped verification

This phase migrates the normal GitHub investigation tools to pinned Git objects,
adds bounded Python function capture, and introduces one deliberately narrow
source-rule verifier. It does not establish arbitrary-PR accuracy or complete
the CodeTurtle 2.0 roadmap.

## Implementation commits

| Commit | Implementation | Full local suite |
| --- | --- | ---: |
| `fa58375` | Pinned PR source/search tools, snapshot-backed Ruby risk/callee reads, early identity checks, no checkout fallback after preparation failure | 701 passed |
| `3afb43c` | Function scopes, absolute citations, dependency gaps, per-hypothesis source requests, oversized-function windows | 714 passed |
| `4b16477` | Narrow BASE/HEAD `len(None)` source verifier with reproducible evidence attribution | 735 passed |
| `b7affa6` | Independently validate proof siblings, repair only invalid decisions, retain partial health, support a proven generic Error claim without rewriting it | 739 passed |
| `834a8eb` | Normalize only the generic error category, retaining raw claims and strict named exceptions | 741 passed |
| `0393f10` | Reject an unestablished caller chain in the direct-invocation source rule | 742 passed |

Native validation first used clean frozen commit
`4b164779378aa49125e45a80484a3016a522b24a`. A second frozen reviewer at `b7affa6`
reuses the same source revisions after fixing the exposed failures. Both runs
are retained. A targeted removed-guard repetition at `834a8eb` follows the generic
category normalization; it is not another independent case. Existing user file
`prf_check.py` was not included in these changes.

## Input and investigation contract

The CLI still prepares its pinned target tip, HEAD, and comparison merge base.
The runtime now checks prepared identities **before** agent work and routes source,
caller/test lexical search, and bounded Ruby callee context through
`SnapshotBundleTools`. Editing a checkout cannot change those observations.
No unversioned graph establishes investigation facts on this path.

When CLI preparation fails, ordinary source tools have no checkout root to fall
back to. Diff investigation can continue, but unavailable source is explicit and
analysis becomes partial. Programmatic legacy callers without snapshot preparation
retain their compatibility path; provenance identifies the source mode.

Existing Ruby risk heuristics now accept a source-reader boundary. Normal PRs
supply Git-object reads. Class-file ambiguity cannot establish a unique callee.
The bounded Ruby method excerpts declare truncation and do not claim resolved
dynamic dispatch. Diff-only rules remain enabled. Checkout-based Ruff execution is
not run on the snapshot investigation path.

## Scoped source capture

`core/input/excerpts.py` parses Python without importing or executing it. When a
file does not fit, it can capture the requested function with its original line
numbers. Each typed observation declares `file`, `python_function`, or `window`
scope, the selected symbol, and unresolved lexical dependencies.

Complete text for one function is not complete repository context. Decorators,
external/dynamic calls, attribute contracts, wildcard imports, enclosing scopes,
shadowed builtins, and dynamic initialization can leave a function inconclusive.
Only an admitted complete function scope with no unresolved lexical dependencies
can be marked successful. This assumes ordinary Python name lookup; runtime
monkey-patching and external caller contracts are not established.

If the function exceeds its line/character budget, the fallback window centers on
the requested operation when possible and stays truncated. Limits were not simply
increased to make results appear complete. Final capture still has a shared
10,000-character budget, at most six paths, and at most 120 lines per source scope.

Source observation IDs include scoped identity and absolute start lines. Historical
whole-file IDs retain their prior shape. Citation validation uses exact original
line ranges. The final verifier's AST guard checks account for the excerpt offset.

Source requests also identify their hypothesis symbol. Two functions in the same
file do not silently share the first function's excerpt. Proof compaction excludes
other symbol-specific source requests while retaining original tool observations.

## Narrow `python-none-len-v1` verifier

This rule verifies an **already proposed candidate**. It does not generate a
candidate or establish general Python defect recall. It admits a single plain,
undecorated module function with one parameter and a direct built-in `len` return.
The candidate must describe the precise None trigger, expected `0`, actual
`TypeError` or generic `Error`, and the exact captured operation. A proven
TypeError entails the generic raised-error description, but does not establish a
different named exception such as ValueError. Original claim fields are retained.
The execution path must contain only the directly invoked function. A caller chain
requires additional evidence and cannot be established by this rule. The final
admission restriction was validated offline against the same seven artifacts;
their observed direct paths remain valid without claiming a new native run.

Supported shapes are deliberately small:

- BASE has `if items is None: return 0`; HEAD directly returns `len(items)`:
  support the introduced failure.
- HEAD still has that guard: refute the claimed None failure with HEAD evidence.
- BASE and HEAD both directly call `len(items)`: identify a preexisting failure.

Extra arguments, async functions, decorators, shadowed builtins, unknown calls,
additional statements, different claims, and unsupported guards do not receive a
rule verdict. They remain the responsibility of normal model verification.

The production runtime enables this rule before a final model request; static-only
mode does not use it to claim model inspection. `finding_source_rules=False`
supports controlled programmatic ablations. Lower-level verifier tests can still
isolate the model path explicitly.

Records identify `verification_method=source_rule` and
`source_rule_id=python-none-len-v1`, retain exact supporting/counter-citations,
and contain no model attempts for that step. Loading the result reproduces the
rule against its recorded observations. Model-origin candidates keep their
original source classification; rule-based verification is a separate attribution.

This resolves a source contract without needing the model to agree. It is not a
claim that local-model reasoning improved. The older model-only failed replays are
preserved unchanged.

## Failures discovered during native validation

The first snapshot PR run returned no verdict after four model requests. Its
JSON was complete, but each proof batch had a decision declaring both a conclusive
status and missing evidence. Whole-batch validation discarded a valid sibling.
The saved response now has a deterministic regression replay.

The fix first validates the exact shared identity envelope. Duplicate, foreign,
missing, or malformed identity membership still rejects the batch. Inside a valid
envelope, each decision independently passes the same schema, coherence, evidence,
and file checks. Valid siblings survive; invalid decisions remain unresolved and
only those IDs can enter the one budgeted repair. No status or evidence field is
corrected. Remaining invalid work produces `PARTIAL`, not a clean empty batch.

The runtime now treats that explicit partial progress as degraded/partial rather
than a total analysis failure. It does not count partial runs as complete source
inspection. A separately verified blocker can still request changes; a partial
empty result cannot become an approval.

The first normal removed-guard CLI run also remained unresolved because its
candidate said generic `Error`, while the source rule admitted only literal
`TypeError`. The narrow entailment fix accepts that generic raised-error outcome
without changing the stored candidate. The original failed model attempts remain
in the first-run artifact. The second run produced lowercase `error`; the final
category normalization admits that generic description without changing its raw
claim or accepting a different named exception. The first preserved-guard control recommended MERGE;
that is one author-defined synthetic control, not a measured false-MERGE rate.

## Validation boundaries

The tests use real Git objects, mutation of checkout files, real shallow-history
preparation, exact citation checks, invalid identity rejection before agent work,
and serialization rechecks. Final-gate tests cover removed/preserved/preexisting
behavior at the top of a file and after 300 lines, plus unsupported forms and
claim mismatches. Model-response fixtures test mechanisms, not model accuracy.

Live results and artifact hashes are in the
[combined manifest](validation/snapshot-context-phase.json). Seven native reviews
contain three distinct underlying cases and 27 recorded model requests.

| Frozen profile | Case | Recommendation / health | Findings | Requests | Command wall seconds |
| --- | --- | --- | ---: | ---: | ---: |
| v1 / `4b16477` | LiteLLM PR | No verdict / failed | 0 | 4 | 205.03 |
| v1 / `4b16477` | Removed guard | COMMENT / partial | 0 | 5 | 68.89 |
| v1 / `4b16477` | Preserved guard | MERGE / completed | 0 | 3 | 41.66 |
| v2 / `b7affa6` | LiteLLM PR | COMMENT / partial | 0 | 4 | 160.06 |
| v2 / `b7affa6` | Removed guard | COMMENT / partial | 0 | 5 | 66.36 |
| v2 / `b7affa6` | Preserved guard | MERGE / completed | 0 | 3 | 40.73 |
| v3 / `834a8eb` | Removed guard | REQUEST_CHANGES / completed | 1 | 3 | 42.63 |

The v2 public PR retains ten unresolved entries and zero recorded inspected units.
Two surviving weak candidates were rejected because their snippets did not match
the reviewed hunk. It is operational recovery to an honest partial result, not a
completed review or a clean-code finding.

The v3 removed-guard finding is generated through normal local CLI discovery and
requirement investigation, then confirmed by `python-none-len-v1`. Its exact
generic `error` claim remains unchanged. No final model request was needed, but
three earlier model requests still occurred. This establishes the narrow source
rule's integration, not a model-reasoning improvement or general latency gain.
The preserved control was not repeated after the v3 category normalization.

The public PR is a development smoke. The removed/preserved cases are existing
synthetic development inputs and are not held-out observations. Requirements are
explicit user-provided review input. Repeated cases must not be counted as new PRs.

## Reproduce through the normal CLI

Use WSL/Bash, a clean chosen reviewer checkout, the installed Python environment,
and a verified reachable Ollama endpoint. The public PR command pins the same
review identities and does not publish:

```bash
.venv/bin/python -m cli.main review https://github.com/BerriAI/litellm/pull/53337 \
  --github-auth gh --dry-run --show-uncertain \
  --expected-head-sha ae0ac16cec6e2ba89c5814f3d1d936db90317582 \
  --expected-base-sha 754c2225d7db8ce71a94459df2216708995c037b \
  --json-output .validation/repeated-pr.json
```

For a fresh development fixture, reuse the existing corpus/materializer and run
the local CLI rather than injecting a model callback:

```python
from pathlib import Path
import subprocess
import sys
from benchmark.requirement_corpus import load_corpus
from benchmark.requirement_experiment import materialize_case

_, cases = load_corpus(Path("benchmark/datasets/requirement_development_v1"))
case = next(item for item in cases if item.case_id == "none-guard-removed")
root = Path(".validation/fresh-none-case").resolve()
root.mkdir(parents=True, exist_ok=False)
base, requirements = materialize_case(root, case)
subprocess.run([
    sys.executable, "-m", "cli.main", "review-local",
    "--repo", str(root), "--base", base,
    "--requirements", str(requirements),
    "--json-output", ".validation/fresh-none-review.json",
], check=True)
```

Choose another fresh directory to repeat the preserved-guard case. New fixture Git
timestamps and absolute paths can change snapshot IDs; compare pinned source
content and diff identity as well as configuration. The recorded experiments
reused the original fixture repos so BASE/HEAD and source identities stayed equal.

## Remaining work

Broader dependency capture and snapshot-qualified graph hints remain incomplete.
Large/complex functions and external contracts can still be unresolved. Model
discovery, proof construction, and unsupported final-verifier decisions still
need quality evaluation. Backend-resolved model citation ranges, explicit
typed outcome categories instead of expanding natural-language aliases,
defective/clean/uncertain truth labels, false-MERGE uncertainty, the real-PR pilot,
durable review jobs, incremental re-review, and release qualification remain later
work. Repository execution is disabled in these diagnostics and is not a security
sandbox for untrusted code.
