# Finding-verifier development validation — 2026-11-21

This phase adds source-bound final decisions, not a demonstrated general accuracy
improvement. The previous live false negative remains preserved. New development
runs include failures and malformed responses, with sealed predictions and
separate scoring. These cases were used for design and prompt iteration.

## Implementation checks

The full local Python 3.12 suite passed **658 tests**, compared with 610 before
this phase. Four stored offline evaluation snapshots also passed. A static-only
CLI review of this implementation produced schema `2.3`, zero model calls, zero
inspected units, zero product findings, and `COMMENT` with partial health.
This smoke run establishes CLI behavior, not reviewer quality.
Four of the added tests execute only the trusted authored development fixtures
in temporary subprocesses: they confirm the removed guard's `TypeError`, preserved
None behavior, cross-tenant leakage after removing a filter, and protection after
delegation. They validate those label semantics without introducing arbitrary PR
execution into prediction or scoring.

Hosted validation initially did not start any jobs because an existing job-level
environment expression used the unavailable `runner` context. Configuration now
initializes in a runner step. The official [context availability table](https://docs.github.com/en/actions/reference/workflows-and-actions/contexts#context-availability)
documents that distinction. Once jobs ran, they exposed an existing Python 3.11
f-string syntax incompatibility and Windows CRLF conversion of hashed JSON files.
The fixes reuse an already-computed regex match and preserve exact dataset/artifact
bytes with `.gitattributes`; hash validation has not been weakened.
The [hosted core validation run](https://github.com/venkatpachala/CodeTurtle/actions/runs/44911060599)
passed all four Windows/Linux and Python 3.11/3.12 matrix jobs at `43b4447`.
The [machine-readable record](validation/2026-11-21-finding-verification.json)
captures that revision, each experiment's frozen revision, counters, and outcomes.

## First complete paired diagnostic

Frozen clean reviewer: `862f7c0`. Model: installed `qwen2.5-coder:7b`, Windows
Ollama transport, temperature 0, seed 42, context 8,192. Four author-labeled
synthetic cases were selected from the twelve-case development corpus: removed
and preserved None guards, removed tenant filter, and delegated tenant guard.
Both variants use requirement investigation; only final-verifier mode varies.

| Measurement | Legacy | Structured prompt v1 |
| --- | ---: | ---: |
| Attempted reviews | 4 | 4 |
| Completed health | 3 | 1 |
| Requirement outcomes matching development labels | 1/4 | 1/4 |
| Product defect findings | 0 | 0 |
| Actual model requests | 19 | 19 |
| Reported prompt tokens | 23,313 | 26,895 |
| Reported completion tokens | 3,979 | 5,361 |
| Model request errors | 0 | 0 |
| Total review wall seconds | 495.585 | 579.020 |

The old verifier again dropped the removed-guard candidate. The structured gate
received an invalid response that copied the example trigger placeholder, then
repeated it during repair. It recorded `invalid_response` and unresolved outcome.
Tenant cases also exposed upstream requirement-citation errors, including altered
quotes and attempted citations to empty observations. Those failures remain in
the denominator; they are not counted as clean outcomes.

The system now reveals these failures, but the first run shows no detection gain.
Paired source identity does not freeze upstream generated candidates or responses.
These are end-to-end development ablations, not causal final-stage isolation.

Artifacts: [manifest](validation/finding-verifier-v1/manifest.json),
[predictions](validation/finding-verifier-v1/predictions.json),
[seal](validation/finding-verifier-v1/seal.json), and
[score](validation/finding-verifier-v1/score.json).

The revised prompt removes the filled-in verdict example, supplies the required
trigger explicitly, and distinguishes observable language semantics from unknown
external behavior. Follow-up measurements must retain their own reviewer commit
and selected-case denominator; they cannot replace the first run's results.

## Revised-prompt follow-up

Frozen clean reviewer: `a5b3395`, prompt `finding-source-v2`, same installed model
and transport profile. This run repeats only the removed/preserved None pair in
both verifier modes, for four reviews. It is a smaller development follow-up,
not a replacement four-case benchmark.

| Measurement | Legacy | Structured prompt v2 |
| --- | ---: | ---: |
| Attempted reviews | 2 | 2 |
| Completed health | 2 | 1 |
| Requirement outcomes matching development labels | 1/2 | 1/2 |
| Product defect findings | 0 | 0 |
| Actual model requests | 7 | 8 |
| Reported prompt tokens | 7,242 | 9,964 |
| Reported completion tokens | 1,522 | 1,976 |
| Model request errors | 0 | 0 |
| Total review wall seconds | 160.994 | 220.386 |

The model now copies the actual trigger and correctly explains that `len(None)`
raises `TypeError`. However, it selects `refuted`, supplies only a supporting
citation, and gives no counterevidence. Its quoted line range is also inconsistent
with its quotation. Repair repeats the invalid response. The validator leaves the
finding unresolved; it does not rewrite the verdict from the rationale or guess
a corrected citation. Preserved-guard satisfaction remains bounded and supported.

This is a real remaining false negative. The phase improves inspectability and
rejects unsupported conclusive decisions; these runs show no detection gain.
Across both runs there were 12 reviews of four distinct development cases and
53 actual model requests, not twelve independent cases.

Artifacts: [manifest](validation/finding-verifier-v2/manifest.json),
[predictions](validation/finding-verifier-v2/predictions.json),
[seal](validation/finding-verifier-v2/seal.json), and
[score](validation/finding-verifier-v2/score.json).

## Reproduce scoring and interpret the evidence

From WSL in the repository, scoring makes no model requests:

```bash
python -m benchmark.requirement_score docs/validation/finding-verifier-v1
python -m benchmark.requirement_score docs/validation/finding-verifier-v2
```

The scorer checks file seals, corpus label identity, complete variant membership,
paired source identity, and the canonical result contract. A successful re-score
establishes artifact consistency. It does not independently adjudicate claims.

Do not turn these development outcomes into headline precision, recall, or a
latency percentile. The cases are synthetic, author-labeled, small, and already
used for design. Model tags are recorded rather than immutable weight digests.
No cloud-model or stronger-model comparison was performed in this phase.

For the next phase, test provider-level constrained structured output and verdict
consistency on the development failures, with a frozen candidate replay to isolate
the final gate. Compare a stronger model under explicit cost limits when available.
Then adjudicate a small set of real development PRs and clean
controls; keep related patches together, freeze inputs/configuration, and measure
finding precision/recall, comments per clean PR, completion rate, actual requests,
tokens, latency, and unresolved reasons. Improve output reliability and scoped
context from those failures before a held-out release evaluation.
