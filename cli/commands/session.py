import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from datetime import datetime

from core.memory.manager import MemoryManager
from core.utils import handle_error

console = Console()
memory = MemoryManager()


def new_session():
    """Start a new conversation/session"""
    try:
        conversation_id = memory.create_new_session()

        # Save as current active session
        try:
            with open(".current_session", "w") as f:
                f.write(conversation_id)
        except Exception as e:
            raise Exception("Failed to save current session") from e

        console.print(Panel.fit(
            f"[bold green]New Session Started[/bold green]\n\n"
            f"Session ID: [cyan]{conversation_id}[/cyan]\n"
            f"Started at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
            f"You can now add repositories using:\n"
            f"[bold]codeturtle add-repo owner/repo[/bold]",
            title="CodeTurtle"
        ))

    except Exception as e:
        handle_error(e)


def list_sessions():
    """List all previous sessions"""
    try:
        from core.memory.database import get_connection

        conn = get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT id, created_at, last_active_at 
            FROM conversations 
            ORDER BY last_active_at DESC
        """)
        sessions = cursor.fetchall()
        conn.close()

        if not sessions:
            console.print(Panel.fit(
                "[yellow]No sessions found yet.[/yellow]\n\n"
                "Start your first session using:\n"
                "[bold]codeturtle new-session[/bold]",
                title="Sessions"
            ))
            return

        table = Table(title="CodeTurtle Sessions")
        table.add_column("Session ID", style="cyan", no_wrap=True)
        table.add_column("Created", style="green")
        table.add_column("Last Active", style="yellow")

        for session in sessions:
            table.add_row(
                session["id"],
                str(session["created_at"]),
                str(session["last_active_at"])
            )

        console.print(table)

    except Exception as e:
        handle_error(e)