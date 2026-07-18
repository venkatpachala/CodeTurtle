import typer
from rich.console import Console
from rich.prompt import Prompt
from pathlib import Path
import os

console = Console()

def init():
    """Initialize codeturrle configuration"""
    console.print(Panel.fit("[bold cyan]codeturrle Initialization[/bold cyan]"))

    config_dir = Path.home() / ".codeturrle"
    config_dir.mkdir(exist_ok=True)

    token = Prompt.ask("Enter your GitHub Token (or press Enter to use GITHUB_TOKEN env)")
    if token:
        os.environ["GITHUB_TOKEN"] = token

    console.print("[green]✓[/green] codeturrle initialized successfully!")
    console.print("You can now run: [bold]codeturrle review owner/repo PR_NUMBER[/bold]")