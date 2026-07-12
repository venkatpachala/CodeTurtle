import typer
from rich.console import Console
from git import Repo
from pathlib import Path
from langchain_community.document_loaders import DirectoryLoader, TextLoader

from core.knowledge_base import KnowledgeBase

console = Console()

def add_repo(
    repo_name: str = typer.Argument(..., help="Repository in format owner/repo"),
):
    """Add a repository and build its knowledge base"""
    console.print(f"[bold cyan]Adding repository:[/bold cyan] {repo_name}")

    repo_path = Path("repos") / repo_name.replace("/", "_")
    
    if repo_path.exists():
        console.print("[yellow]Repository already exists locally. Skipping clone.[/yellow]")
    else:
        console.print("[yellow]Cloning repository...[/yellow]")
        repo_url = f"https://github.com/{repo_name}.git"
        Repo.clone_from(repo_url, repo_path)
        console.print("[green]Repository cloned successfully.[/green]")

    # Load all code files with proper encoding handling
    console.print("[yellow]Loading and embedding codebase...[/yellow]")
    
    loader = DirectoryLoader(
        str(repo_path),
        glob="**/*",
        loader_cls=TextLoader,
        loader_kwargs={
            "encoding": "utf-8",
            "autodetect_encoding": True,   # ← Important fix
        },
        show_progress=True,
        use_multithreading=True,
        silent_errors=True,                # ← Skip files that fail to load
    )
    
    documents = loader.load()

    if not documents:
        console.print("[red]No documents were loaded. Please check the repository.[/red]")
        return

    # Create knowledge base
    kb = KnowledgeBase(collection_name=repo_name.replace("/", "_"))
    kb.add_documents(documents)

    console.print(f"[bold green]✓ Knowledge base created successfully for {repo_name}[/bold green]")
    console.print(f"[dim]Total documents loaded: {len(documents)}[/dim]")