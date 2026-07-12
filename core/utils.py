from rich.console import Console
from rich.panel import Panel
import sys

console = Console()

def handle_error(error: Exception, verbose: bool = False):
    """Centralized error handler with better GitHub support"""
    
    error_str = str(error).lower()
    
    # GitHub Authentication Errors
    if "github" in error_str or "bad credentials" in error_str or "401" in error_str:
        console.print(Panel.fit(
            "[red]GitHub Authentication Failed[/red]\n\n"
            "Your GitHub token is invalid, expired, or has insufficient permissions.\n\n"
            "**Quick fixes:**\n"
            "1. Generate a new classic token with `public_repo` scope\n"
            "2. Make sure the token is correctly pasted in `.env`\n"
            "3. For fine-grained tokens, grant access to the specific repository\n\n"
            "Run with `--verbose` to see the exact error from GitHub.",
            title="Error"
        ))
        
        if verbose:
            console.print("\n[bold red]Actual GitHub Error:[/bold red]")
            console.print_exception(show_locals=False)
        return

    # Other existing error cases...
    if "no active session" in error_str or ".current_session" in error_str:
        console.print(Panel.fit(
            "[red]No active session found![/red]\n\n"
            "Please start a new session first:\n"
            "[bold]codeturtle new-session[/bold]",
            title="Error"
        ))
    
    elif "ollama" in error_str or "connection refused" in error_str:
        console.print(Panel.fit(
            "[red]Could not connect to Ollama.[/red]\n\n"
            "Please make sure Ollama is running:\n"
            "[bold]ollama serve[/bold]",
            title="Error"
        ))
    
    else:
        console.print(Panel.fit(
            f"[red]Something went wrong.[/red]\n\n{str(error)}",
            title="Error"
        ))
        
        if verbose:
            console.print_exception(show_locals=False)
    
    sys.exit(1)