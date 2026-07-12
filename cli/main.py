import typer
from rich.console import Console

from cli.commands import review, init, add_repo   # ← Added add_repo

app = typer.Typer(
    name="reviewforge",
    help="ReviewForge - Local Agentic Code Review System",
    add_completion=False,
)

app.command()(init.init)
app.command()(review.review)
app.command()(add_repo.add_repo)   # ← New command

if __name__ == "__main__":
    app()