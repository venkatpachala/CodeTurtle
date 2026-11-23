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
