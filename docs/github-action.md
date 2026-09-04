# CodeTurtle GitHub Action (6.3a)

Run CodeTurtle on `pull_request` **opened / synchronize / reopened** and post one review (`--comment`) with the same 6.1 summary + 6.2 inlines as the CLI.

Local CLI still defaults to `--dry-run`. The Action passes `--comment` on purpose.

This is **not** a GitHub App. Do not use `pull_request_target` (untrusted code + secrets).

## Add to a repo you own

1. Copy [`examples/github-action.yml`](../examples/github-action.yml) to:

   `.github/workflows/codeturtle-review.yml`

2. Repository variable `CODETURTLE_GIT` = git URL of CodeTurtle (the tool), e.g. `https://github.com/YOU/codeturtle.git`.

   If the workflow is **in the CodeTurtle repo itself**, `uv sync` is used instead.

3. Permissions are already in the YAML:

   ```yaml
   permissions:
     contents: read
     pull-requests: write
   ```

4. Token:

   - Default `GITHUB_TOKEN` can comment on PRs in the same repo when `pull-requests: write` is set.
   - If `create_review` returns **403**, add a classic PAT with `public_repo` (or fine-grained PR write) as secret **`CODETURTLE_GITHUB_TOKEN`**. Resolution order: `CODETURTLE_GITHUB_TOKEN`, then `GITHUB_TOKEN`.

5. Graphify: the job tries `graphify . --code-only` in the PR tree and sets `GRAPHIFY_GRAPH_PATH` to `$GITHUB_WORKSPACE/graphify-out/graph.json` (Phase 1 setting; no `repos/` layout required).

7. Optional repo policy: commit `.codeturtle.yaml` at the repo root (see `docs/codeturtle-yaml.md`). The Action sets `CODETURTLE_CONFIG` to that path; if the file is missing, review continues with defaults.

6. LLM: GitHub-hosted runners do **not** have Ollama. Point `LLM_BACKEND` / `OPENAI_API_KEY` at a cloud model, or use a **self-hosted runner** that already runs Ollama.

## What the Action does not do (defaults)

- No `--execute-install` / `--execute-tests` (untrusted PR code). Turn on later with `workflow_dispatch` input `execute_tests`.
- Skips **drafts** unless you set env `CODETURTLE_REVIEW_DRAFTS=true`.
- Skips **`dependabot[bot]`**.
- Does not review **fork** PRs with write secrets (`pull_request` only).

## Session

CI has no `.current_session`. `review` **creates a session** if the file is missing. You do not need `new-session` in the workflow.

## Idempotency

Same 6.1 marker + **head SHA**. A `synchronize` with a new SHA posts a new review; the same SHA is skipped.

## Live check

Open a small PR on **your** repo that changes one `.py` file. Actions tab should go green; the PR should show a CodeTurtle review (summary + optional inlines). Push another commit (new SHA) → another review.
