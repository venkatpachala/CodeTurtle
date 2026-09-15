# CodeTurtle

Local-first GitHub pull request reviewer.

Deterministic gates (PR facts, path grounding, hunk verification, coverage clamp)
plus a specialist agent swarm. Structure comes from Graphify. Reviews run on
your machine. Nothing is posted unless you pass `--comment`.

```bash
uv tool install git+https://github.com/venkatpachala/CodeTurtle.git@v0.2.0
codeturtle review owner/repo 123 --dry-run
```

## What is CodeTurtle?

CodeTurtle is a CLI. It fetches a GitHub PR with your token, builds a
code-only Graphify graph of the repository, reviews **change units** (hunks)
instead of a truncated diff, and emits **MERGE**, **COMMENT**, or
**REQUEST_CHANGES**.

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
- GitHub token with `public_repo` (or fine-grained PR read)
- An LLM: Ollama (default) or OpenAI-compatible
- Graphify code-only graph for the repo you review

### Install

```bash
uv tool install git+https://github.com/venkatpachala/CodeTurtle.git@v0.2.0

# from a clone
git clone https://github.com/venkatpachala/CodeTurtle.git
cd CodeTurtle
pip install -e ".[ollama,graphify]"
codeturtle --help
```

### Setup

```bash
cp .env.example .env
# set GITHUB_TOKEN
# OLLAMA_MODEL=qwen2.5:7b
ollama pull qwen2.5:7b
```

Index structure once per repo:

```bash
git clone https://github.com/owner/repo repos/owner_repo
cd repos/owner_repo
graphify . --code-only
```

Qdrant and Neo4j are not required for `--help` or `--dry-run`.

### Review

```bash
codeturtle new-session
codeturtle review owner/repo 123 --dry-run
codeturtle review owner/repo 123 --comment
codeturtle graphify-test owner/repo --stats
```

Default is dry-run. `--comment` on a repo without write access fails closed and prints the body.

### Smoke test (v0.2.0)

| Field | Value |
|-------|--------|
| PR | [confident-ai/deepeval#3288](https://github.com/confident-ai/deepeval/pull/3288) |
| Classification | source |
| Change units | 2 |
| Investigate | 6 hops |
| Decision | REQUEST_CHANGES |
| Graphify | ~19k nodes / ~57k edges |
| Post | none (`--dry-run`) |

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

