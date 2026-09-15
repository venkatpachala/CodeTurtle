"""First-run menu: token, model, review. No new-session ceremony."""

from __future__ import annotations

import os
import subprocess
from typing import List, Optional

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt

from config import settings
from core.user_config import (
    config_path,
    detect_github_token,
    save_user_config,
)

console = Console()


def list_ollama_models(ollama_bin: str = "ollama") -> List[str]:
    try:
        proc = subprocess.run(
            [ollama_bin, "list"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    if proc.returncode != 0:
        return []
    names: List[str] = []
    for i, line in enumerate((proc.stdout or "").splitlines()):
        line = line.strip()
        if not line:
            continue
        name = line.split()[0]
        if i == 0 and name.lower() in {"name", "model"}:
            continue
        if name:
            names.append(name)
    return names


def _token_status() -> str:
    tok = detect_github_token()
    if tok:
        return "detected"
    return "missing"


def _ensure_token() -> str:
    existing = detect_github_token()
    if existing:
        os.environ["GITHUB_TOKEN"] = existing
        settings.github_token = existing
        save_user_config({"github_token": existing})
        console.print(f"[green]GitHub token[/green] detected → {config_path()}")
        return existing
    console.print(
        "Paste a GitHub token (classic `public_repo`, or [bold]Enter[/bold] to try [cyan]gh auth token[/cyan])."
    )
    pasted = Prompt.ask("GitHub token", password=True, default="").strip()
    token = pasted or detect_github_token()
    if not token:
        console.print("[red]No GitHub token. Set GITHUB_TOKEN or run gh auth login.[/red]")
        return ""
    os.environ["GITHUB_TOKEN"] = token
    settings.github_token = token
    save_user_config({"github_token": token})
    console.print(f"[green]Saved[/green] {config_path()}")
    return token


def _ensure_model() -> str:
    current = (getattr(settings, "ollama_model", "") or "").strip()
    models = list_ollama_models()
    if not models:
        console.print(
            "[yellow]Install Ollama and pull a model — you cannot ship 5GB weights inside uv tool install.[/yellow]\n"
            "  https://ollama.com/download\n"
            "  ollama pull qwen2.5:7b"
        )
        if current:
            return current
        fallback = Prompt.ask("Model name", default=current or "qwen2.5:7b").strip()
        if fallback:
            settings.ollama_model = fallback
            settings.llm_backend = "ollama"
            os.environ["OLLAMA_MODEL"] = fallback
            save_user_config({"ollama_model": fallback, "llm_backend": "ollama"})
        return fallback
    console.print("[bold]Ollama models[/bold]")
    for i, name in enumerate(models, start=1):
        mark = " [green](current)[/green]" if name == current else ""
        console.print(f"  {i}. {name}{mark}")
    default = "1"
    if current in models:
        default = str(models.index(current) + 1)
    raw = Prompt.ask("Pick a model", default=default).strip()
    chosen = current or models[0]
    if raw.isdigit() and 1 <= int(raw) <= len(models):
        chosen = models[int(raw) - 1]
    elif raw in models:
        chosen = raw
    settings.ollama_model = chosen
    settings.llm_backend = "ollama"
    os.environ["OLLAMA_MODEL"] = chosen
    save_user_config({"ollama_model": chosen, "llm_backend": "ollama"})
    console.print(f"[green]Model[/green] {chosen}")
    return chosen


def _run_review(repo: str, number: int) -> None:
    from cli.commands.review import ReviewPipeline

    ReviewPipeline().run(
        repo=repo,
        number=number,
        dry_run=True,
        verbose=False,
        execute_tests=False,
        execute_install=False,
        comment=False,
        config_path="",
    )


def _prompt_pr() -> Optional[tuple[str, int]]:
    repo = Prompt.ask("Repository (owner/repo)", default="").strip().strip("/")
    if not repo or "/" not in repo:
        console.print("[red]Expected owner/repo (e.g. confident-ai/deepeval).[/red]")
        return None
    raw = Prompt.ask("PR number", default="").strip()
    try:
        number = int(raw)
    except ValueError:
        console.print("[red]PR number must be an integer.[/red]")
        return None
    if number <= 0:
        console.print("[red]PR number must be positive.[/red]")
        return None
    return repo, number


def run_wizard() -> None:
    console.print(
        Panel.fit(
            "[bold cyan]CodeTurtle[/bold cyan]\n"
            "Local PR review. Graphify + your model. Default is dry-run.",
            title="Welcome",
        )
    )
    while True:
        token_state = _token_status()
        model = (getattr(settings, "ollama_model", "") or "").strip() or "not set"
        console.print()
        console.print(f"  [1] GitHub token      {token_state} → {config_path()}")
        console.print(f"  [2] Model             {model}")
        console.print("  [3] Review a PR       owner/repo  N")
        console.print("  [4] Quit")
        choice = Prompt.ask("Select", choices=["1", "2", "3", "4"], default="3")
        if choice == "1":
            _ensure_token()
        elif choice == "2":
            _ensure_model()
        elif choice == "3":
            if not detect_github_token():
                if not _ensure_token():
                    continue
            if not (getattr(settings, "ollama_model", "") or "").strip():
                _ensure_model()
            picked = _prompt_pr()
            if not picked:
                continue
            repo, number = picked
            _run_review(repo, number)
        else:
            return
