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

        # Clone if not exists
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

        # Only load text/code files (ignore images, binaries, etc.)
        console.print("[yellow]Loading and embedding codebase (this may take a while)...[/yellow]")

        loader = DirectoryLoader(
            str(repo_path),
            glob="**/*.{py,md,txt,rst,yaml,yml,json,toml,cfg,ini,sh}",
            loader_cls=TextLoader,
            loader_kwargs={
                "encoding": "utf-8",
                "autodetect_encoding": True,
            },
            show_progress=True,
            use_multithreading=True,
            silent_errors=True,
        )

        documents = loader.load()

        if not documents:
            raise Exception("No text documents found in the repository.")

        # Create knowledge base
        collection_name = repo_name.replace("/", "_")
        kb = KnowledgeBase(collection_name=collection_name)
        kb.add_documents(documents)

        console.print(Panel.fit(
            f"[bold green]✓ Knowledge base created successfully[/bold green]\n\n"
            f"Repository: {repo_name}\n"
            f"Documents loaded: {len(documents)}",
            title="Success"
        ))

    except Exception as e:
        handle_error(e)