# CodeTurtle v0.4 ship notes

CLI reviewer. Default dry-run. Decision is Policy. Coverage is observational.

## Install

```text
uv tool install "git+https://github.com/venkatpachala/CodeTurtle.git@v0.4.0"
```

Default install includes `langchain-ollama` and `graphifyy[mcp]`. Optional extra `[openai]` for OpenAI-compatible servers.

## Needs

- `GITHUB_TOKEN` (or `gh auth login`)
- Ollama (`OLLAMA_MODEL`, default from `~/.codeturtle/config.toml`) or `OPENAI_API_KEY`
- First PR on a repo builds Graphify `--code-only` once (minutes). Qdrant is not required.

## Flags

| Flag | Effect |
|------|--------|
| `--dry-run` | Default. No `create_review`. |
| `--comment` | Post summary (inlines only if snippet line resolved). |
| `--execute-tests` | Jailed pytest on related tests in a detached worktree. |
| `--execute-install` | `uv sync` / pip in that worktree. Never a green skip. |
| `--show-uncertain` | Print PLAUSIBLE drops. They never set Decision. |

## Execute skip reasons

`flag_off` `lockfile-only` `no_test_targets` `checkout_failed` `no_installer` `install_failed` `deps_missing` `timeout` `path_jail`

`deps_missing` only when `--execute-install` was **off**. If install is on, logs are `install start` then `install ok` or `install_failed` / `no_installer`.

## Comments

Posted/printed COMMENTS are **VERIFIED_BUG** only. Line is the snippet’s RIGHT-side line, never the change-unit start.

## Limits

No extra agents. Coverage never REQUEST_CHANGES. Poetry/npm postinstall/full-suite CI are out of v0.4.
