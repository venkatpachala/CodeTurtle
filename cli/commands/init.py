import os
import shutil
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt

console = Console()


def init():
    """Write ~/.codeturtle/config.toml and an example .codeturtle.yaml."""
    console.print(Panel.fit("[bold cyan]CodeTurtle Initialization[/bold cyan]"))

    from core.user_config import config_path, ensure_home, save_user_config

    ensure_home()
    token = Prompt.ask(
        "Enter your GitHub Token (or press Enter to use GITHUB_TOKEN env)",
        default="",
    ).strip()
    payload = {"llm_backend": "ollama", "ollama_model": "qwen2.5-coder:7b"}
    if token:
        os.environ["GITHUB_TOKEN"] = token
        payload["github_token"] = token
    save_user_config(payload)
    console.print(f"[green]Wrote[/green] {config_path()}")

    dest = Path.cwd() / ".codeturtle.yaml"
    example_src = Path(__file__).resolve().parents[2] / "examples" / "codeturtle.yaml"
    if dest.exists():
        console.print(f"[dim]kept existing {dest}[/dim]")
    elif example_src.is_file():
        shutil.copyfile(example_src, dest)
        console.print(f"[green]Wrote[/green] {dest}")
    else:
        dest.write_text(
            "version: 1\nskip_drafts: true\nexecute_tests: false\n"
            "execute_install: false\n# model: qwen2.5-coder:7b\n",
            encoding="utf-8",
        )
        console.print(f"[green]Wrote[/green] {dest}")

    console.print(
        "Next: [bold]codeturtle review https://github.com/org/repo/pull/123 --dry-run[/bold]"
    )