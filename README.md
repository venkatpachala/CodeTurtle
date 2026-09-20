# CodeTurtle

Local-first GitHub PR review CLI. **Decision is Policy**. Comments are verified defects only.

```text
Install
  uv tool install "git+https://github.com/venkatpachala/CodeTurtle.git@v0.4.0"

Needs
  GITHUB_TOKEN
  Ollama (OLLAMA_MODEL) or OPENAI_API_KEY
  First PR on a repo builds Graphify once (minutes)

Review
  codeturtle review https://github.com/org/repo/pull/123 --dry-run -v

Post (your repo only)
  codeturtle review YOU/REPO 12 --comment
```

`codeturtle` with no arguments opens a wizard (token → model → paste URL → always dry-run first). Default is **dry-run**. Nothing is posted unless you pass `--comment`.

---

## What is CodeTurtle?

CodeTurtle is a local-first CLI that fetches a GitHub PR, builds a code-only Graphify knowledge graph of the repository, and reviews **change units** (hunks) in impl+test bundles through the **v4 ReviewRuntime** — a deterministic pipeline with no LangGraph dependency on the default path.

**Decision is Policy.** `MERGE`, `COMMENT`, or `REQUEST_CHANGES` is set by deterministic code from facts, not by LLM confidence. The model only writes comment text on `KEEP`-passing, fully verified findings.

Config lives in `%USERPROFILE%\.codeturtle\config.toml` (or `~/.codeturtle/config.toml`).

### What gets filtered out

- A finding that only cites `.github/wordlist.txt`, lockfiles, or trivial files is dropped.
- Lockfile-only PRs never open investigation and never receive `APPROVE` or `REQUEST_CHANGES`.
- `KEEP` is not proof — a claim must be token-supported by the actual diff hunk.
- Low change-unit coverage cannot `MERGE` on an empty finding set.
- Draft PRs are skipped by default (`skip_drafts: true` in `.codeturtle.yaml`).

There is no required backend. Optional Langfuse traces LLM calls if you set keys.

---

## Architecture

### v4 ReviewRuntime pipeline

The default runtime (`runtime: v4`) is a linear, LangGraph-free pipeline:

```text
PR Facts & Change Units
  ↓
BundleBuilder       group source + test hunks into impl/test bundles (max 4)
  ↓
Rule Engine         deterministic rules fire first, no LLM
  ↓
BundleAgent         per-bundle LLM agent with Graphify + DiffIndex tools (max 4 steps)
  ↓
Proof Gate          incomplete_proof candidates dropped before position lookup
  ↓
Positioner          resolve exact diff line for each candidate
  ↓
Reflector           path-jail, hunk-support, and lockfile guards
  ↓
Verify Loop         cross-check claims against DiffIndex; Graphify MCP for uncertain ones
  ↓
Sandbox (opt-in)    jailed pytest on PR worktree; evidence only, never disproves a finding
  ↓
Policy / decide()   MERGE | COMMENT | REQUEST_CHANGES from facts, coverage, tests
```

The legacy 17-node LangGraph path remains available via `runtime: legacy` in `.codeturtle.yaml`.

### Deterministic layers

| Layer | Who decides | Examples |
|-------|-------------|----------|
| Facts | code | `files_changed`, lockfile vs source, `DiffIndex` |
| Structure | Graphify MCP | callers, neighbors, `graph.json` |
| Candidates | `BundleAgent` + rule engine | per-bundle findings with proof fields |
| Gates | code | path jail, hunk support, proof completeness, coverage clamp |
| Voice | LLM | comment text on `KEEP` + verified findings only |

The model does not own file selection, line identity, or the final GitHub event type.

### Candidate lifecycle

Each candidate raised by the agent or rule engine passes through these gates in order:

1. **Classify** — non-defect kinds (`note`) are dropped immediately.
2. **Proof Gate** — `proof_complete()` checks all required structured fields; incomplete candidates are dropped with reason `incomplete_proof`.
3. **Positioner** — resolves a `+`-side diff line number; no line → dropped.
4. **Reflector** — checks path-jail (file in PR), hunk token support, bundle path alignment.
5. **Verify Loop** — stamps each candidate `verified` / `uncertain` / `disproved`; Graphify MCP hops used for uncertain claims (bounded: max 6 calls, 30 s).
6. **Sandbox** — optional pytest run; failure sets `tests_failed` policy reason; pass does not disprove a finding.
7. **Policy** — `decide()` maps coverage + findings + execution into the final decision.

### Graphify MCP integration

Graphify is included in the default install. On first review of a repo, CodeTurtle clones into `~/.codeturtle/repos/` and runs `graphify extract . --code-only` to build `graphify-out/graph.json`. The `GraphifyMCPProvider` connects via stdio and exposes `get_node`, `get_neighbors`, `query`, `shortest_path`, and `get_pr_impact` to agents and the verify loop.

---

## How to use

### Prerequisites

- Python >= 3.11
- git
- GitHub token with `public_repo` (or fine-grained PR read), or `gh auth login`
- An LLM: [Ollama](https://ollama.com/download) (`ollama pull qwen2.5:7b`) or `OPENAI_API_KEY`

### Install

```bash
uv tool install "git+https://github.com/venkatpachala/CodeTurtle.git@v0.4.0"
codeturtle
```

From a clone:

```bash
git clone https://github.com/venkatpachala/CodeTurtle.git
cd CodeTurtle
pip install -e .
codeturtle --help
```

Graphify is included in the default install — no separate step needed.

### Commands

```bash
# Interactive wizard (first-run setup)
codeturtle

# Review a PR (all three URL forms are accepted)
codeturtle review owner/repo 123 --dry-run
codeturtle review owner/repo#123 --dry-run
codeturtle review https://github.com/owner/repo/pull/123 --dry-run -v

# Post a review to GitHub (requires write access or PR ownership)
codeturtle review owner/repo 123 --comment

# Optional sandbox: run related tests inside a jailed worktree
codeturtle review owner/repo 123 --dry-run --execute-tests
codeturtle review owner/repo 123 --dry-run --execute-tests --execute-install

# Verify Graphify is reachable for a repo
codeturtle graphify-test owner/repo --stats

# Register a local clone manually
codeturtle add-repo owner/repo /path/to/local/clone

# Session management
codeturtle new-session
codeturtle list-sessions
```

Default is **dry-run**. `--comment` on a repo without write access fails closed and prints the review body.

### CLI flags

| Flag | Default | Description |
|------|---------|-------------|
| `--dry-run` | `true` | Print the review body without posting to GitHub |
| `--comment` | `false` | Post the review to GitHub |
| `--execute-tests` | `false` | Opt-in sandbox: jailed pytest on PR's related tests only |
| `--execute-install` | `false` | Install deps before running tests (implies network) |
| `--config PATH` | auto | Path to a `.codeturtle.yaml` policy file |
| `-v / --verbose` | `false` | Emit debug-level logs |

### Environment variables

| Variable | Description |
|----------|-------------|
| `GITHUB_TOKEN` | GitHub personal access token (`public_repo` scope minimum) |
| `OLLAMA_MODEL` | Ollama model name (default: `qwen2.5:7b`) |
| `OLLAMA_BASE_URL` | Ollama server URL (default: `http://localhost:11434`) |
| `LLM_BACKEND` | `ollama` (default) or `openai` |
| `GRAPHIFY_GRAPH_PATH` | Path to `graphify-out/graph.json` for the target repo |
| `CODETURTLE_CONFIG` | Path to a `.codeturtle.yaml` repo policy file |

### Repo policy (`.codeturtle.yaml`)

Drop a `.codeturtle.yaml` at your repo root (see [`examples/codeturtle.yaml`](examples/codeturtle.yaml) and [`docs/codeturtle-yaml.md`](docs/codeturtle-yaml.md) for the full reference). Key fields:

| Field | Effect |
|-------|--------|
| `skip_drafts` | Skip draft PRs |
| `skip_authors` | Skip bot accounts (e.g. `dependabot[bot]`) |
| `ignore_paths` | Drop paths from `files_changed` and the rebuilt diff |
| `inline_max` | Cap on inline comments posted (default 8) |
| `execute_tests` / `execute_install` | Turn sandbox on without a CLI flag |
| `model` | Override the Ollama model for this repo |
| `coverage_merge_min` | Min packed/total ratio required to `MERGE` on empty finding set (default 0.5) |
| `runtime` | `v4` (default) or `legacy` (17-node LangGraph graph) |
| `bundle_max` | Max review bundles (default 4) |
| `agent_max_steps` | Max BundleAgent tool steps per bundle (default 4) |

Config merge order (later wins): `Settings / .env` → `environment variables` → `.codeturtle.yaml` → **CLI flags**.

### Sandbox (optional)

`--execute-tests` runs a path-jailed pytest inside a detached Git worktree at the PR head SHA. Key guarantees:

- No `shell=True`; timeout enforced.
- A **green** run is evidence, never auto-approves or disproves an existing finding.
- A **red** run sets `Decision = REQUEST_CHANGES` with reason `tests_failed`.
- Lockfile-only PRs skip execution entirely.
- Skip is never counted as a green test run.

### GitHub Action

Copy [`examples/github-action.yml`](examples/github-action.yml) to `.github/workflows/codeturtle-review.yml`. The Action runs on `pull_request` (opened / synchronize / reopened), builds Graphify in the PR checkout, and posts with `--comment`. See [`docs/github-action.md`](docs/github-action.md) for full setup.

### Dev eval

```bash
uv run python -m tests.evaluation.run_eval --offline
```

---

## Repository layout

```text
cli/            Typer entry point (codeturtle)
  commands/     review, add-repo, graphify-test, inspect-kb, session, wizard
core/
  runtime/      ReviewRuntime (v4), verify_loop, qualify, pipeline models
  agent/        BundleAgent, BundleTools, contract (proof_complete, classify_kind)
  bundling/     BundleBuilder — groups change units into impl+test bundles
  review/       ReviewFinding, PipelineTrace, TimingRecord
  verification/ DiffIndex, policy (decide), execute (sandbox pytest)
  rules/        deterministic rule engine (no LLM)
  graphctx/     symbol helpers for Graphify context
  repository_knowledge/  GraphifyMCPProvider, RepositoryKnowledgeProvider
  graphify_retriever.py  Graphify-by-identifier retrieval
  reflector.py  path-jail + hunk-support reflector gate
  positioner.py diff line resolver
  pr_facts.py   PR classification and facts builder
  change_units.py  hunk → change unit extraction
docs/           architecture, CLI reference, .codeturtle.yaml, GitHub Action
examples/       .codeturtle.yaml template, GitHub Action workflow
tests/          unit tests and golden offline eval
evals/          phase benchmark scripts
scripts/        maintainer helpers
```

---

## Documentation

- [Architecture](docs/architecture.md)
- [CLI reference](docs/cli.md)
- [`.codeturtle.yaml` policy](docs/codeturtle-yaml.md)
- [GitHub Action](docs/github-action.md)
- [Ship validation](docs/SHIP_VALIDATION.md)

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).
