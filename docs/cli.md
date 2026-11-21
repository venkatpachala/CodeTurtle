# CLI Reference

Configure credentials in `.env` — see [`.env.example`](../.env.example).

## WSL client with Ollama on Windows

The normal CLI uses `OLLAMA_BASE_URL` through the native Ollama provider; the
benchmark's PowerShell bridge is a separate transport. In WSL NAT mode, Windows
services are reached through the Windows host IP rather than assuming WSL
`localhost` reaches them. See [Microsoft's WSL networking documentation](https://learn.microsoft.com/en-us/windows/wsl/networking).

Inspect the current host address from WSL with `ip route show default`. Verify
`http://HOST_IP:11434/api/tags` is reachable and the requested model is installed,
then save the endpoint and model in the WSL user's `~/.codeturtle/config.toml`:

```toml
llm_backend = "ollama"
ollama_model = "qwen2.5-coder:7b"
ollama_base_url = "http://HOST_IP:11434"
```

Replace `HOST_IP` with the verified address. Environment variables override the
user configuration. The address can change after WSL/network restarts; this
configuration does not implement automatic rediscovery. No model API key is
required for this local Ollama connection.

The gateway keeps its historical positive `retries` values as a total-attempt
budget. Values `0` and `1` each allow one request; zero disables retries rather
than disabling generation. An explicit value `2` allows at most two attempts.
Review budget accounting still applies separately to logical stage requests.

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
| `--execute-tests` | `False` | Opt-in sandbox: jailed pytest on this PR’s related tests only |
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
