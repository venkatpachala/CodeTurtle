# Preview release checklist

## Local verification

```powershell
New-Item -ItemType Directory -Force .validation | Out-Null
uv run python -m pytest tests/test_production_contract.py tests/test_phase72_change_units.py tests/test_v4_bundles.py tests/test_v4_reflector.py tests/test_v4_symbols.py tests/test_v4_url_parse.py tests/evaluation/test_scorer.py -q -p no:cacheprovider
uv run python -m scripts.validate_production_live --output .validation/live.json
uv build --out-dir .validation/dist
uv venv .validation/clean-install
uv pip install --python .validation/clean-install/Scripts/python.exe .validation/dist/codeturtle_review-0.5.0a1-py3-none-any.whl
```

Run the installed entrypoint from a directory outside the source tree. Inspect
`health`, `result`, `publication_preview`, and `publication` in the JSON output.
The non-mocked suite deliberately excludes historical tests using canned model
callbacks, fake clients, monkeypatching, and stub runners.

## GitHub verification

```powershell
codeturtle review owner/repo 123 --github-auth gh --dry-run --json-output review.json
codeturtle review owner/repo 123 --github-auth gh --comment --json-output review.json
```

Choose a disposable PR you control before exercising live publication. The
delivery validation script can reconcile duplicates, reject stale/wrong targets,
and optionally post a clearly labeled non-defect inline test annotation:

```powershell
uv run python -m scripts.validate_github_delivery review.json --output delivery.json --exercise-inline
```

Confirm a single grouped review with the correct commit, summary, and inlines.
Replay and verify the review count does not grow. Push a new commit on the test
PR to validate a new legitimate SHA separately; stale-plan rejection alone does
not test the new-commit lifecycle. Verify permissions and fork behavior.

## Evaluation and release

1. Freeze exact PR revisions and input hashes; keep gold labels separate.
2. Keep related patch lineages in the same partition.
3. Add adjudicated clean controls. Do not treat bug-only benchmarks as clean evidence.
4. Seal predictions before scoring. Inspect text-overlap matches manually.
5. Run development-only `python -m benchmark.ablate --help` experiments sequentially.
6. Compare adjudicated outcomes with `python -m benchmark.release BASELINE CANDIDATE --output gate.json`.
7. Commit/freeze the selected implementation and configuration before held-out testing.
8. Require measured, passing gates; null denominators are unmeasured.
9. Publish dataset/model/prompt/scorer/reviewer identities and limitations.
10. Start with dry-run/shadow mode, then comments. Approval remains a separate opt-in.

## Rollback

Disable manual publishing, select the previous audited tooling revision, and retain
the failed run artifacts. Never overwrite benchmark predictions to make a release pass.
