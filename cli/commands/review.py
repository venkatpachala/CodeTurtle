import typer
from rich.console import Console
from rich.panel import Panel
from rich.markdown import Markdown
from github import Github

from config import settings
from core.llm import get_llm
from core.state import ReviewState
from core.graph import review_graph

console = Console()

def review(
    repo: str = typer.Argument(..., help="Repository (owner/repo)"),
    number: int = typer.Argument(..., help="PR or Issue number"),
    dry_run: bool = typer.Option(True, "--dry-run", help="Don't post comments to GitHub"),
):
    """Run ReviewForge Swarm on a GitHub PR/Issue using local Ollama"""
    
    console.print(Panel.fit(
        f"[bold cyan]ReviewForge Swarm[/bold cyan]\n"
        f"Repository: {repo}#{number}\n"
        f"Model: {settings.ollama_model} (Ollama)"
    ))
    
    try:
        # Fetch PR data
        g = Github(settings.github_token)
        repo_obj = g.get_repo(repo)
        pr = repo_obj.get_pull(number)
        
        # Build initial state
        state = ReviewState(
            repo=repo,
            number=number,
            title=pr.title,
            body=pr.body or "",
            author=pr.user.login,
            diff=pr.get_files()[0].patch if pr.get_files() else None,  # simplified
            files_changed=[f.filename for f in pr.get_files()],
            model_used=settings.ollama_model
        )
        
        console.print("[yellow]Running agent swarm...[/yellow]")
        
        # Run the LangGraph
        final_state = review_graph.invoke(state)
        
        # Display results beautifully
        console.print("\n[bold green]=== CONTEXT SUMMARY ===[/bold green]")
        console.print(Markdown(final_state["context_summary"]))
        
        console.print("\n[bold green]=== CODE QUALITY ANALYSIS ===[/bold green]")
        console.print(Markdown(final_state["code_analysis"]))

        console.print("\n[bold green]=== CRITIQUE ===[/bold green]")
        console.print(Markdown(final_state["critique"]))

        console.print("\n[bold cyan]=== FINAL RECOMMENDATION & COMMENT ===[/bold cyan]")
        console.print(Markdown(final_state["final_comment"]))
        
        console.print("\n[bold cyan]Review completed successfully![/bold cyan]")
        
        if not dry_run:
            console.print("[red]Posting to GitHub not implemented yet (coming soon).[/red]")
        else:
            console.print("[dim]--dry-run mode: No comment posted.[/dim]")
            
    except Exception as e:
        console.print(f"[red]Error:[/red] {str(e)}")
        console.print("Make sure Ollama is running and your model is pulled.")