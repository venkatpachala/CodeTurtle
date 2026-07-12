import typer
from rich.console import Console
from rich.panel import Panel

from cli.commands import review, init, add_repo, session
from core.utils import handle_error

app = typer.Typer(
    name="codeturtle",
    help="CodeTurtle - Local Agentic Code Review & Repository Intelligence System",
    add_completion=False,
)

# Register all commands
app.command(name="new-session")(session.new_session)
app.command(name="list-sessions")(session.list_sessions)
app.command()(init.init)
app.command()(review.review)
app.command()(add_repo.add_repo)


@app.callback(invoke_without_command=True)
def main(ctx: typer.Context):
    """Global entry point with error handling"""
    if ctx.invoked_subcommand is None:
        console = Console()
        console.print(Panel.fit(
            "[bold cyan]CodeTurtle[/bold cyan]\n\n"
            "Use [bold]codeturtle --help[/bold] to see available commands.\n"
            "Start with: [bold]codeturtle new-session[/bold]",
            title="Welcome"
        ))


if __name__ == "__main__":
    try:
        app()
    except Exception as e:
        from core.utils import handle_error
        handle_error(e, verbose=False)