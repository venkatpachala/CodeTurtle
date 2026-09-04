# `.codeturtle.yaml` (Phase 6.4)

A repo can declare how CodeTurtle reviews it. The CLI and the GitHub Action both load the same file.

## Merge order

Later wins:

1. `config.py` / `Settings` (including `.env`)
2. Environment variables
3. `.codeturtle.yaml` (or `--config` / `CODETURTLE_CONFIG`)
4. **CLI flags** (highest): `--dry-run` / `--comment`, `--execute-tests`, `--execute-install`

Missing file = today’s behavior. Unknown YAML keys are ignored. Invalid YAML or wrong types **fail startup** (the file is not silently dropped).

Do not put API keys in YAML.

## Where it is found

1. `--config PATH`
2. `CODETURTLE_CONFIG`
3. `./.codeturtle.yaml` then `./.codeturtle.yml` in **cwd**
4. In CI: set `CODETURTLE_CONFIG` to `$GITHUB_WORKSPACE/.codeturtle.yaml` (absent file is OK)

CodeTurtle does not read YAML from a random `repos/` clone unless that tree is the cwd under review.

Template: [`examples/codeturtle.yaml`](../examples/codeturtle.yaml).

## Fields

| Field | Effect |
|--------|--------|
| `skip_drafts` | If the PR is a draft and this is true → skip, exit 0, no post |
| `skip_authors` | If `pr.user.login` matches (case-insensitive) → skip |
| `ignore_paths` | Dropped from `files_changed` and the rebuilt diff **after** GitHub fetch. Classification, grounding, hunks, and inlines all see the **filtered** list |
| `inline_max` | Cap on 6.2 inline comments |
| `inline_lockfile` | Default false |
| `execute_tests` / `execute_install` | YAML `true` can turn execute **on** without a flag (dangerous). CLI `--execute-tests` still turns it on even if YAML is false |
| `model` | Chat model name for this run (`settings.ollama_model`) |
| `post_on_github` | Does **not** override CLI `--dry-run`. Do not rely on this alone to post |
| `coverage_merge_min` | Optional. Empty KEEP may MERGE only if `units_packed / units_total` ≥ this (default `0.5`). Low coverage is COMMENT, never REQUEST_CHANGES |

## `ignore_paths` and lockfiles

If you ignore `**/package-lock.json` and the PR only touches that file, CodeTurtle logs `[Review] skip reason=all_files_ignored` and exits 0. It will **not** KEEP the lockfile.

If markdown is ignored but `.py` files remain, classification uses the remaining source files.

Golden eval (QueryWeaver 571) does **not** load this template. Do not put an ignore-lockfile YAML in the CodeTurtle repo root if you want eval/review of lockfile PRs from that cwd.

## CLI vs YAML posting

```text
--dry-run              never posts (even if post_on_github: true)
--comment              posts
YAML post_on_github    not sufficient by itself
```

The Action still passes `--comment`. It also sets `CODETURTLE_CONFIG` so the reviewed checkout’s YAML is used when present.
