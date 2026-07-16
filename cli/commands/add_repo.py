import typer
from rich.console import Console
from rich.panel import Panel
from git import Repo, GitCommandError
from pathlib import Path

from core.repository_intelligence import RepositoryIntelligence
from core.utils import handle_error

console = Console()


def add_repo(
    repo_name: str = typer.Argument(..., help="Repository in format owner/repo"),
):
    """Add a repository and build its knowledge base using the Repository Intelligence pipeline."""

    try:
        console.print(Panel.fit(
            f"[bold cyan]Adding Repository[/bold cyan]\n\n{repo_name}",
            title="CodeTurtle"
        ))

        repo_path = Path("repos") / repo_name.replace("/", "_")

        # Clone repository if not exists
        if repo_path.exists():
            console.print("[yellow]Repository already exists locally. Skipping clone.[/yellow]")
        else:
            console.print("[yellow]Cloning repository...[/yellow]")
            try:
                repo_url = f"https://github.com/{repo_name}.git"
                Repo.clone_from(repo_url, repo_path)
                console.print("[green]Repository cloned successfully.[/green]")
            except GitCommandError as e:
                raise Exception(f"Failed to clone repository: {repo_name}") from e

        # Use the new Repository Intelligence Pipeline
        intelligence = RepositoryIntelligence(
            repo_path=str(repo_path),
            repo_name=repo_name
        )

        intelligence.index_repository()

        console.print(Panel.fit(
            f"[bold green]✓ Repository Intelligence Pipeline completed successfully[/bold green]\n\n"
            f"Repository: {repo_name}\n"
            f"Total files indexed: {intelligence.repository_model.total_files}",
            title="Success"
        ))

    except Exception as e:
        handle_error(e)