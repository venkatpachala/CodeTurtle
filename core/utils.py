from rich.console import Console
from rich.panel import Panel
import sys

console = Console()

def handle_error(error: Exception, verbose: bool = False):
    """Centralized error handler with clear, actionable messages"""
    
    error_str = str(error).lower()
    
    # Session related
    if "no active session" in error_str or ".current_session" in error_str:
        console.print(Panel.fit(
            "[red]No active session found![/red]\n\n"
            "Please create a new session:\n"
            "[bold]codeturtle new-session[/bold]",
            title="Error"
        ))
    
    # Ollama related
    elif "ollama" in error_str or "connection refused" in error_str:
        console.print(Panel.fit(
            "[red]Could not connect to Ollama.[/red]\n\n"
            "Make sure Ollama is running:\n"
            "[bold]ollama serve[/bold]\n\n"
            "And your model is downloaded:\n"
            "[bold]ollama pull qwen2.5:7b[/bold]",
            title="Error"
        ))
    
    # Knowledge Base related
    elif "knowledge base" in error_str or "collection" in error_str:
        console.print(Panel.fit(
            "[red]Knowledge base not found for this repository.[/red]\n\n"
            "Please add the repository first:\n"
            "[bold]codeturtle add-repo owner/repo[/bold]",
            title="Error"
        ))
    
    # GitHub related
    elif "github" in error_str or "token" in error_str:
        console.print(Panel.fit(
            "[red]GitHub authentication failed.[/red]\n\n"
            "Please check your GitHub token in the `.env` file.\n"
            "It needs at least `public_repo` scope.",
            title="Error"
        ))
    
    # Repository not found
    elif "not found" in error_str and "repo" in error_str:
        console.print(Panel.fit(
            "[red]Repository not found.[/red]\n\n"
            "Please check the repository name (format: owner/repo).",
            title="Error"
        ))
    
    else:
        # Generic fallback
        console.print(Panel.fit(
            f"[red]An unexpected error occurred.[/red]\n\n{str(error)}",
            title="Error"
        ))
        
        if verbose:
            console.print_exception(show_locals=False)
    
    sys.exit(1)