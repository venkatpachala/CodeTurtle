# CLI Reference

Configure credentials in `.env` — see [`.env.example`](../.env.example).

## Commands

### `new-session`

Start a new review session (resets session state).

```bash
codeturtle new-session
```

---

### `review`

Review a GitHub pull request.

```bash
codeturtle review owner/repo 123 --dry-run
codeturtle review owner/repo#123 --dry-run
codeturtle review https://github.com/owner/repo/pull/123 --dry-run
```

Default runtime is **v4**. Printed `Decision:` is Policy (`MERGE` / `COMMENT` / `REQUEST_CHANGES`), not leftover LLM Final text. Set `runtime: legacy` in `.codeturtle.yaml` to use the 17-node graph.

**Options**

| Flag | Default | Description |
|------|---------|-------------|
| `--dry-run` | `True` | Print the review body without posting to GitHub |
| `--comment` | `False` | Post the review to GitHub (requires write access or PR ownership) |
| `--execute-tests` | `False` | Run the PR's test suite in an isolated worktree |
| `--execute-install` | `False` | Install dependencies before running tests (implies network) |
| `--config PATH` | auto | Path to a `.codeturtle.yaml` policy file |
| `-v / --verbose` | `False` | Emit debug-level logs |

`--comment` on a repo without write access fails closed and prints the review body instead.

---

### `graphify-test`

Verify that the Graphify MCP server is reachable for a repo.

```bash
codeturtle graphify-test owner/repo --stats
```

---

### `add-repo`

Register a local clone for a repo slug so CodeTurtle can locate the Graphify graph.

```bash
codeturtle add-repo owner/repo /path/to/local/clone
```

---

## Environment variables

See [`.env.example`](../.env.example) for the full list. Key variables:

| Variable | Description |
|----------|-------------|
| `GITHUB_TOKEN` | GitHub personal access token (`public_repo` scope minimum) |
| `OLLAMA_MODEL` | Ollama model name (default: `qwen2.5:7b`) |
| `OLLAMA_BASE_URL` | Ollama server URL (default: `http://localhost:11434`) |
| `LLM_BACKEND` | `ollama` (default) or `openai` |
| `GRAPHIFY_GRAPH_PATH` | Path to `graphify-out/graph.json` for the target repo |
