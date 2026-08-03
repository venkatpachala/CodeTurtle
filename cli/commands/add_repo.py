import typer
from rich.console import Console
from rich.panel import Panel
from git import Repo, GitCommandError
from pathlib import Path

from core.utils import handle_error
from core.repository_intelligence.service import RepositoryIntelligenceService

console = Console()


def add_repo(
    repo_name: str = typer.Argument(..., help="Repository in format owner/repo"),
    force: bool = typer.Option(True, "--force/--no-force", help="Force full re-index"),
):
    """Add a repository and build its knowledge base using Repository Intelligence."""

    try:
        console.print(
            Panel.fit(
                f"[bold cyan]Adding Repository[/bold cyan]\n\n{repo_name}",
                title="CodeTurtle",
            )
        )

        repo_path = Path("repos") / repo_name.replace("/", "_")

        # Clone if needed (CLI responsibility; service owns indexing)
        if repo_path.exists():
            console.print(
                "[yellow]Repository already exists locally. Skipping clone.[/yellow]"
            )
        else:
            console.print("[yellow]Cloning repository...[/yellow]")
            try:
                repo_url = f"https://github.com/{repo_name}.git"
                Repo.clone_from(repo_url, repo_path)
                console.print("[green]Repository cloned successfully.[/green]")
            except GitCommandError as e:
                raise Exception(f"Failed to clone repository: {repo_name}") from e

        svc = RepositoryIntelligenceService(repo_name)
        result = svc.index(force=force, repo_path=str(repo_path))

        if not result.success:
            console.print(f"[red]Index failed:[/red] {result.message}")
            for err in result.errors:
                console.print(f"  • {err}")
            raise SystemExit(1)

        console.print(
            Panel.fit(
                f"[bold green]✓ Repository Intelligence Pipeline completed successfully[/bold green]\n\n"
                f"Repository: {result.repo_name}\n"
                f"Total files indexed: {result.files_indexed}\n"
                f"Symbols: {result.symbols}\n"
                f"{result.message}",
                title="Success",
            )
        )

    except Exception as e:
        handle_error(e)