import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from pathlib import Path

from core.repository_persistence import RepositoryPersistence
from core.repository_model import RepositoryModel
from core.utils import handle_error

console = Console()


def inspect_kb(
    repo_name: str = typer.Argument(..., help="Repository in format owner/repo"),
    stats: bool = typer.Option(False, "--stats", help="Show repository statistics"),
    symbols: bool = typer.Option(False, "--symbols", help="Show symbols"),
    search: str = typer.Option(None, "--search", help="Search for term"),
):
    """Inspect the knowledge base for a repository."""

    try:
        console.print(Panel.fit(
            f"[bold cyan]Inspecting Knowledge Base[/bold cyan]\n\n{repo_name}",
            title="CodeTurtle"
        ))

        # Load persisted repository model
        persistence = RepositoryPersistence(repo_name)
        repository_model = persistence.load_repository_model()

        if repository_model is None:
            raise Exception(f"Repository {repo_name} has not been indexed yet. Run add-repo first.")

        if stats or not (symbols or search):
            show_stats(repository_model)

        if symbols:
            show_symbols(repository_model)

        if search:
            search_kb(repository_model, search)

    except Exception as e:
        handle_error(e)


def show_stats(repository_model: RepositoryModel):
    """Show basic repository statistics."""
    table = Table(title="Repository Statistics")
    table.add_column("Metric", style="cyan")
    table.add_column("Value", style="green")

    table.add_row("Files", str(repository_model.total_files))
    table.add_row("Languages", ", ".join(repository_model.languages))
    table.add_row("Indexed At", str(repository_model.indexed_at))
    table.add_row("Symbols", str(sum(len(f.symbols) for f in repository_model.files)))

    console.print(table)


def show_symbols(repository_model: RepositoryModel):
    """Show top symbols."""
    console.print("[yellow]Top Symbols (limited):[/yellow]")
    count = 0
    for fm in repository_model.files:
        for symbol in fm.symbols:
            if count >= 20:
                return
            console.print(f"  {symbol.type}: {symbol.name} ({fm.path})")
            count += 1


def search_kb(repository_model: RepositoryModel, term: str):
    """Simple search in repository model."""
    console.print(f"[yellow]Searching for '{term}':[/yellow]")
    found = 0
    for fm in repository_model.files:
        if term.lower() in fm.path.lower() or term.lower() in fm.preview.lower():
            console.print(f"  Found in {fm.path}")
            found += 1
            if found >= 10:
                break
    if found == 0:
        console.print("[dim]No matches found.[/dim]")