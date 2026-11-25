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
ollama_context_tokens = 8192
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

Inside an existing **WSL/Bash** terminal, run Python directly. Bash uses a trailing
backslash for continuation:

```bash
.venv/bin/python -m cli.main review https://github.com/BerriAI/litellm/pull/53337 \
  --github-auth gh --dry-run --show-uncertain \
  --json-output .validation/my-pr-review.json
```

From **PowerShell**, this equivalent single line launches WSL:

```powershell
wsl.exe -d Ubuntu --cd /home/venkat/projects/CodeTurtle .venv/bin/python -m cli.main review https://github.com/BerriAI/litellm/pull/53337 --github-auth gh --dry-run --show-uncertain --json-output .validation/my-pr-review.json
```

PowerShell backticks entered in Bash perform command substitution. If Bash is
waiting at a `>` continuation prompt after a malformed command, press Ctrl+C and
run the Bash command above. HTTP 200, CLI exit zero, and partial COMMENT have
different meanings: inspect the JSON health, unresolved records, and product
findings before interpreting the result.

The normal PR path prepares historical comparison objects before model calls.
It attempts finite fetch depths 32, 128, and 512 within a bounded preparation
budget. Missing history remains explicit. Proof requests use small typed batches
and at most one repair per bundle; unresolved work cannot imply clean code.

The review policy sets the printed recommendation (`MERGE`, `COMMENT`, or `REQUEST_CHANGES`). Remove the retired `runtime: legacy` setting from existing configurations.

**Options**

| Flag | Default | Description |
|------|---------|-------------|
| `--dry-run` | `True` | Print the review body without posting to GitHub |
| `--comment` | `False` | Post the review to GitHub (requires write access or PR ownership) |
| `--execute-tests` / `--execute-install` | `False` | Legacy flags rejected by `review`. Use `sandbox-check` with a digest-pinned image |
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
| `OLLAMA_CONTEXT_TOKENS` | Explicit Ollama context window (default: 8192; allowed 1024–32768) |
| `LLM_BACKEND` | `ollama` (default) or `openai` |
| `GRAPHIFY_GRAPH_PATH` | Path to `graphify-out/graph.json` for the target repo |
