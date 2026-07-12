import typer
from rich.console import Console
from rich.panel import Panel
from git import Repo, GitCommandError
from pathlib import Path
from langchain_community.document_loaders import DirectoryLoader, TextLoader

from core.knowledge_base import KnowledgeBase
from core.utils import handle_error

console = Console()


def add_repo(
    repo_name: str = typer.Argument(..., help="Repository in format owner/repo"),
):
    """Add a repository and build its knowledge base"""

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

        # Load documents with robust error handling
        console.print("[yellow]Loading and embedding codebase...[/yellow]")

        loader = DirectoryLoader(
            str(repo_path),
            glob="**/*",
            loader_cls=TextLoader,
            loader_kwargs={
                "encoding": "utf-8",
                "autodetect_encoding": True,
            },
            show_progress=True,
            use_multithreading=True,
            silent_errors=True,           # Skip files that fail to load
        )

        documents = loader.load()

        if not documents:
            raise Exception("No documents could be loaded from the repository.")

        # Create knowledge base
        collection_name = repo_name.replace("/", "_")
        kb = KnowledgeBase(collection_name=collection_name)
        kb.add_documents(documents)

        console.print(Panel.fit(
            f"[bold green]✓ Successfully created knowledge base[/bold green]\n\n"
            f"Repository: {repo_name}\n"
            f"Documents loaded: {len(documents)}\n"
            f"Collection: {collection_name}",
            title="Success"
        ))

    except Exception as e:
        handle_error(e)