# CodeTurtle GitHub Action

The provided workflow runs on opened, synchronized, and reopened pull requests
from the same repository. Automatic runs write a dry-run artifact. Manual
dispatch also accepts a PR number and an explicit publication option.

## Setup

1. Copy [the example](../examples/github-action.yml) to
   `.github/workflows/codeturtle-review.yml`.
2. Set the repository variable `CODETURTLE_REV` to the full commit SHA of
   CodeTurtle you want the workflow to install.
3. Add the `OPENAI_API_KEY` secret. Set the optional `OPENAI_MODEL` variable
   to override the example's default model.
4. Open a same-repository PR and download `review.json` from the workflow's
   artifacts. To post the review, run the workflow manually with `publish`
   enabled.

## Runtime and delivery

The workflow installs the reviewer from the selected commit and runs the same
CLI as a local review. The example disables Graphify and leaves PR code
execution to the separate `sandbox-check` command. The workflow skips
automatic reviews for draft and fork PRs and cancels older runs for the
same PR. The CLI also applies its Dependabot skip rule in GitHub Actions.

For live delivery, the CLI rechecks PR revisions and reconciles duplicates
using the reviewed revision, publication plan, and publisher identity.
The workflow uploads the canonical JSON with health, findings, and the
delivery outcome when one was produced.
