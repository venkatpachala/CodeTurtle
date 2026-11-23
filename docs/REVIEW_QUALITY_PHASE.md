# Review quality improvements

## Implementation

This phase adapts scope accounting, bounded context retrieval, and separate
position resolution from the Open Code Review study. CodeTurtle continues to use
the existing Python runtime, pinned Git input adapters, SQLite jobs, final
verification and product policy.
[Open Code Review source](https://github.com/alibaba/open-code-review/tree/e74f2c6bd4422bd1e12d257d1725bcce1d6b9ddd)

### Scope and admission

Change units retain original hunk length, the number of source characters
preserved by the prefix excerpt, and an explicit clipping flag. An assessment
over a clipped excerpt remains visible with `excerpt_truncated` and contributes
zero full-inspection credit. Inspection records count excluded kinds and retain
budget or missing-evidence reasons for eligible units. The existing format
remains readable through additive fields. SQL, Prisma schemas, Docker/Compose
definitions and workflow YAML enter source classification.

Bundle formation can attach a differently named test to the single source
group that declares a symbol it references. Ordinary filename matching remains
in effect. Ambiguous symbols do not establish a cross-file relationship.

### Budgeting

Semantic discovery and its repair are limited by bundle steps. Up to two
regression leads per bundle can enter source investigation, with one bounded
schema repair, within the shared review call ceiling. At a twelve-call cap,
initial reservations leave six calls for discovery while holding four for
investigation and two for final verification. Investigation can use other
unused capacity while retaining the verification reservation. Call reservations
by lane appear in the canonical result. Reservations can remain unspent when
the reviewer finds no leads. All lanes share the existing cumulative prompt
and wall-clock checks.

### Contract context

Local review reads context from pinned Git source. The pilot's remote adapter
adds bounded tree enumeration around changed files and conventional directories,
then opens at most 36 source-context files. The remote inventory is explicitly
limited. Search favors distinct unchanged related paths and test assertions
over imports, records exact revision and blob identity, and includes a small
context window. Discovery queries the active batch and receives focused review
questions for visibly changed storage operations and schemas. Proof gets the
contract context for its selected symbol. Final verification can read up to
two related unchanged paths in addition to operator-supplied context.
Lexical references can guide reasoning; they do not establish resolved call edges.

### Proof spans and policy

The proof path reads BASE and HEAD around the relevant hunk. It constructs
bounded spans from numbered source lines and binds IDs to the snapshot,
revision, path, blob hash and range. The provider schema restricts each side to
its own supplied IDs. The backend resolves the range and applies the existing
transition checks. One malformed proof response per bundle can be repaired
against the same catalog. Existing final verification still determines whether
a candidate enters product output. Reported discovery evidence gaps also
prevent full inspection credit, even when the rest of the assessment is valid.

## Reproduce the comparison

Use a clean checkout of each recorded reviewer revision and one configured
model. The comparison preserves the historical test split and uses the
previously unused validation split of the frozen pilot. Both profiles use one
bundle and two discovery/agent steps. Candidate semantic proof calls are
scheduled in separate lanes within the same global ceiling.

```bash
python -m benchmark.blind_pilot benchmark/datasets/real_pilot_v1 \
  --split validation --output validation-output
python -m benchmark.pilot benchmark/datasets/real_pilot_v1 \
  --predictions validation-output/predictions.json \
  --annotations docs/validation/efficient-reviewer-v1/published-labels/annotations.json
```

The scorer exposes admission, inspection gaps, hypotheses, proof outcomes,
candidate conversion, final verification, calls, tokens and latency. A finding
on an externally labeled PR still needs issue-level matching to establish
recall or precision. Unlabeled controls are excluded from clean-PR conclusions.

## Results

The full suite passed **848 tests**, including live Docker checks, on the code
revision containing the synchronization guard. The original 30-PR test split
was replayed offline for scope accounting. Eligible count changed from 392 to
399. Full-inspection credit fell from 84 to 71 on the original assessments,
removing the 13 clipped credits. Both saved six-line proof rejections accepted
and resolved backend span IDs in a schema-only replay.

### Matched ten-PR validation

The paired live run used baseline `461daa8` and candidate `c56f333`.
Both reviewers assessed the same pinned validation split, using the same
Ollama GPU endpoint, Qwen model digest, bundle limit and shared call ceiling.
This is a comparison of the combined changes. It does not isolate causes of
the latency difference or control for every warm-up or network effect.

| Measure | Baseline | Candidate |
| --- | ---: | ---: |
| Sealed results | 10 | 10 |
| Eligible units | 183 | 183 |
| Packed units | 119 | 121 |
| Admitted units | 30 | 30 |
| Inspected under each implementation | 27 | 17 |
| Inspected after applying current clipping rules offline | 21 | 17 |
| Hypotheses | 3 | 2 |
| Proofs with model conclusions | 1 | 2 |
| Proofs lost to budget | 2 | 0 |
| Agent candidates and verified product findings | 0 | 0 |
| Published issue matches | 0 of 22 | 0 of 22 |
| False-MERGE on externally labeled defective PRs | 1 of 5 | 1 of 5 |
| Source API requests | 241 | 406 |
| Budgeted model calls | 16 | 18 |
| Reported prompt and completion tokens | 43,563 | 54,915 |
| Case latency p50 | 44.4 s | 54.5 s |
| Case latency p95 | 169.4 s | 222.6 s |

The new budget reached both candidate leads, and both proof answers refuted
their specific lead. Final verification received zero candidates. The stronger
scope accounting and evidence handling did not produce a measured quality or
latency gain on this split. Five of the ten cases lacked accepted clean or
defect labels. The candidate's false-MERGE is the same Grafana case observed by
the baseline. This supports a process and safety diagnosis with a small labeled
denominator.
[Sealed comparison](validation/review-quality-v2/comparison.json)

### Follow-up safety guard

Both frozen validation results credited the two units of Grafana #90939 as
inspected and recommended MERGE. The changed hunks expose new synchronization
boundaries. The follow-up prioritizes these changes and requires human review
when recognizable synchronization changes have no verified blocker. This is
a deterministic policy guard. A policy replay against the saved assessment
and a new native run on the same pinned revisions both returned COMMENT
with `synchronization_change_requires_review`. The new run emitted zero
findings. The pair remains sealed at its original revision.
[Grafana policy replay and native rerun](validation/review-quality-v2/lock-guard/check.json)

### Known miss and synthetic controls

On the previously exposed Cal.com #14943 case, the candidate returned COMMENT
and emitted no findings. Discovery used two calls and generated zero
hypotheses. The persistence guard still applied. This remains a discovery miss.

On the two existing synthetic development families, native Qwen found the
expiry regression, returned no findings on either repair, and left the
signed-delta regression unresolved during final verification. Independent
Docker BASE/HEAD oracles passed for all four cases. A separate
`gpt-6-astra` reference answered both unique synthetic discovery questions
using the captured question evidence and schema. Native discovery also
selected the expected side on all four directional cases. The stronger-model
reference comparison covers discovery only. It supplies no real-PR
or final-verifier accuracy estimate.
[Synthetic oracles](validation/review-quality-v2/synthetic-oracles.json)
· [Matched synthetic responses](validation/review-quality-v2/synthetic-reference.json)
