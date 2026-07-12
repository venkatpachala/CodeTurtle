from rich.console import Console
from rich.panel import Panel
import sys

console = Console()

def handle_error(error: Exception, verbose: bool = False):
    """Central error handler with user-friendly messages"""
    
    error_msg = str(error)
    
    # Common known errors
    if "No active session" in error_msg or ".current_session" in error_msg:
        console.print(Panel.fit(
            "[red]No active session found![/red]\n\n"
            "Please start a new session first:\n"
            "[bold]codeturtle new-session[/bold]",
            title="Error"
        ))
    
    elif "ollama" in error_msg.lower() or "connection refused" in error_msg.lower():
        console.print(Panel.fit(
            "[red]Could not connect to Ollama.[/red]\n\n"
            "Please make sure Ollama is running:\n"
            "[bold]ollama serve[/bold]\n\n"
            "And that your model is pulled:\n"
            "[bold]ollama pull qwen2.5:7b[/bold]",
            title="Error"
        ))
    
    elif "knowledge base" in error_msg.lower() or "collection" in error_msg.lower():
        console.print(Panel.fit(
            "[red]Knowledge base not found for this repository.[/red]\n\n"
            "Please add the repository first:\n"
            "[bold]codeturtle add-repo owner/repo[/bold]",
            title="Error"
        ))
    
    elif "github" in error_msg.lower() or "token" in error_msg.lower():
        console.print(Panel.fit(
            "[red]GitHub authentication failed.[/red]\n\n"
            "Please check your GitHub token in `.env` file.\n"
            "Make sure it has `public_repo` scope.",
            title="Error"
        ))
    
    else:
        # Generic error
        console.print(Panel.fit(
            f"[red]Something went wrong.[/red]\n\n{error_msg}",
            title="Error"
        ))
        
        if verbose:
            console.print_exception()
    
    sys.exit(1)