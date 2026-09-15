# Contributing

## Setup

Python 3.11+.

```bash
uv sync
pip install -e ".[ollama,graphify]"
```

`codeturtle --help` must work.

## Checks before PR

```bash
codeturtle --help
uv run python -m tests.evaluation.run_eval --offline
```

Both must pass. Do not commit `.env` or tokens.

## Reviews

Default is `--dry-run`. Do not `--comment` on repos you do not own.

## Issues

Paste `--dry-run -v` logs with tokens redacted.
