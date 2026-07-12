import typer
from rich.console import Console
from rich.panel import Panel
from rich import print as rprint

from config import Settings
from cli.commands import review, init

app = typer.Typer(
    name="reviewforge",
    help="ReviewForge Swarm — Autonomous GitHub Community Reviewer",
    add_completion=False,
)
console = Console()

app.command()(init.init)
app.command()(review.review)

if __name__ == "__main__":
    app()