# Real-PR pilot: annotation protocol

The registry contains 60 pinned candidate inputs in 60 patch families, with
20 development / 10 validation / 30 test cases. It does not contain 40 confirmed
defective and 20 confirmed clean PRs. Those are proposed sampling strata only.

The collector inspected 90 candidates, retained 66 eligible pinned inputs, and
selected 60 representatives deterministically. Collection failures/ineligibility
are retained in `collection.json`. Scope excludes PRs with over 100 files, over
1 MB collected patch text, no supported code patch, or unavailable code patches.
This is a purposive pilot, not a representative estimate for all GitHub PRs.

`inputs.json` records BASE, HEAD, comparison merge base, canonical patch digest,
family identity, sampling stratum, and known exposure. `patches/` contains the
captured public patches; source URLs are recorded per case. Original project
licensing continues to apply to source excerpts. No review comments or source
gold annotations are passed to prediction through this registry.

All 60 entries in `annotations.pending.json` are pending. Venkat is the available
human reviewer; no independent human audit is claimed. Complete an annotation only
after checking the pinned source, reachable trigger and BASE/HEAD attribution:

1. Audit prior exposure and aliases. Known exposed cases are development-only;
   unknown exposure blocks headline use. Do not tune on validation/test outputs.
2. Label `defective` only for a demonstrated introduced actionable defect. Record
   source paths/lines, a concrete trigger, consequence, and why BASE differs.
3. Label `reviewed_clean` only after the planned review scope and checks are
   complete. Missing source comments, a merged PR, a model's empty review, or a
   passing existing test suite does not establish a clean label. Use `uncertain`
   when a necessary contract or dependency remains unresolved.
4. Record labelers and supporting evidence. If only Venkat adjudicates, report an
   author-adjudicated pilot. Record unresolved disagreement as uncertain.
5. Keep annotations separate from prediction inputs. Seal one prediction artifact
   per selected case, including failed/no-verdict attempts, before scoring.

An adjudicated entry has this shape (replace every placeholder with real audit
data; this example is not an annotation):

```json
{
  "status": "adjudicated",
  "exposure_audit": "passed",
  "truth": {
    "label": "uncertain",
    "base_sha": "<exact frozen BASE>",
    "head_sha": "<exact frozen HEAD>",
    "labelers": ["<actual reviewer>"],
    "evidence": ["<source audit or isolated reproducer artifact>"],
    "rationale": "<what was established and what remains unknown>"
  },
  "issue_labels": []
}
```

Use `python -m benchmark.pilot ROOT --predictions progress.json --seal --output
sealed.json --split test` to seal complete frozen-profile predictions. Use the
same command without `--seal`, with `--predictions sealed.json --annotations
ANNOTATIONS.json`, to report safety accounting. Seals validate source identities,
profile consistency, complete case accounting and checksums. They do not certify
human label correctness. The safety report does not substitute for issue-level
precision/recall, independent label audit, or a qualified release.

Actual held-out predictions have not been generated while exposure and annotation
audits remain pending. This prevents treating an unfinished experiment as a result.
