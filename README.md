# CodeTurtle

Local-first GitHub PR reviewer. Graphify structure. **Decision is Policy** (`MERGE` / `COMMENT` / **REQUEST_CHANGES**), not leftover LLM Final text. Default **v4** runtime. Runs on your machine.

```bash
uv tool install "git+https://github.com/venkatpachala/CodeTurtle.git@v0.3.0"
codeturtle
```

Requires: **Ollama** (or `OPENAI_API_KEY`), **git**, and a **GitHub token** (`gh auth login` or paste once).

`codeturtle` with no arguments opens a menu: save token → pick an Ollama model → paste `owner/repo N`, `owner/repo#N`, or a GitHub pull URL. The CLI clones into `~/.codeturtle/repos/`, checks out the PR SHA, builds a Graphify code-only graph if the SHA changed, and dry-runs the review.

```text
CodeTurtle
  [1] GitHub token      detected / paste once → ~/.codeturtle/config.toml
  [2] Model             list from Ollama: qwen2.5:7b, llama3.2, ...
  [3] Review a PR       owner/repo  3292
  [4] Quit
```

Scripts still work:

```bash
codeturtle review owner/repo 123 --dry-run
codeturtle review owner/repo#123 --dry-run
codeturtle review https://github.com/owner/repo/pull/123 --dry-run
```

Default is **dry-run** and **v4** (`ReviewRuntime`: bundles → Graphify-by-identifier → reflector → Policy). Nothing is posted unless you pass `--comment`. Qdrant is off on the default path. Set `runtime: legacy` in `.codeturtle.yaml` for the 17-node LangGraph.

Optional sandbox (default **off**): `--execute-tests` runs jailed pytest on this PR’s related tests in a detached worktree at `pr.head.sha`. `--execute-install` may sync uv/npm in that worktree only. A green run is evidence and never auto-MERGEs. A red run can set Decision to `REQUEST_CHANGES` (`tests_failed`). Decision is still Policy.

---

## What is CodeTurtle?

CodeTurtle is a CLI. It fetches a GitHub PR with your token, builds a
code-only Graphify graph of the repository, reviews **change units** (hunks)
in impl+test bundles, and prints **Decision** from Policy: **MERGE**, **COMMENT**, or
**REQUEST_CHANGES**.

Config lives in `%USERPROFILE%\.codeturtle\config.toml` (or `~/.codeturtle/config.toml`), not a random project `.env`.

Agents propose findings. Gates decide what ships:

- a finding that only cites `.github/wordlist.txt` is dropped
- lockfile-only PRs never open investigation and cannot APPROVE or REQUEST_CHANGES
- "supported" means the claim tokens appear in the actual hunk — KEEP is not proof
- low change-unit coverage cannot MERGE on an empty finding set

It is not a hosted SaaS reviewer. There is no required backend. Optional Langfuse
traces LLM calls if you set keys.

## Why this shape?

### What goes wrong with a plain LLM wrapper

- reviews the wrong file (docs, lockfile, wordlist)
- invents symbols that are not in the PR
- MERGE because the model sounded confident
- one 14k-character slice of a 100k diff

### Deterministic engineering × agents

| Layer | Who decides | Examples |
|-------|-------------|----------|
| Facts | code | files_changed, lockfile vs source, DiffIndex |
| Structure | Graphify MCP | callers, neighbors, graph.json |
| Hypotheses | agents + extractors | specialists, failure-path seeds on delete/load |
| Gates | code | path jail, hunk support, coverage clamp |
| Voice | LLM | comment text on KEEP and supported findings only |

The model does not own file selection, line identity, or the final GitHub event type.

## How to use

### Prerequisites

- Python >= 3.11
- git
- GitHub token with `public_repo` (or fine-grained PR read), or `gh auth login`
- An LLM: [Ollama](https://ollama.com/download) (`ollama pull qwen2.5:7b`) or `OPENAI_API_KEY`

You cannot ship a 7B model inside `uv tool install`. Ollama (or an API key) is the only extra install.

### Install

```bash
uv tool install "git+https://github.com/venkatpachala/CodeTurtle.git@v0.3.0"
codeturtle
```

From a clone:

```bash
git clone https://github.com/venkatpachala/CodeTurtle.git
cd CodeTurtle
pip install -e .
codeturtle --help
```

Graphify is included in the default install.

### Commands

```bash
codeturtle
codeturtle review owner/repo 123 --dry-run
codeturtle review owner/repo#123 --dry-run
codeturtle review https://github.com/owner/repo/pull/123 --dry-run
codeturtle review owner/repo 123 --dry-run --execute-tests
codeturtle review owner/repo 123 --comment
codeturtle graphify-test owner/repo --stats
```

Default is dry-run. `--comment` on a repo without write access fails closed and prints the body.

### Dev eval

```bash
uv run python -m tests.evaluation.run_eval --offline
```

## Repository layout

```text
cli/          # Typer entry (`codeturtle`)
core/         # review engine, Graphify, gates
docs/         # architecture, CLI, ship notes
examples/     # GitHub Action, .codeturtle.yaml
tests/        # unit tests and golden eval
evals/        # optional phase scripts
scripts/      # maintainer helpers
```

## Documentation

- [Architecture](docs/architecture.md)
- [CLI](docs/cli.md)
- [Ship validation](docs/SHIP_VALIDATION.md)
- [Repo policy](examples/codeturtle.yaml)
- [GitHub Action](examples/github-action.yml)

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).
