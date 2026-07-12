import typer
from rich.console import Console

from cli.commands import review, init, add_repo, session

app = typer.Typer(
    name="codeturtle",
    help="CodeTurtle - Local Agentic Code Review & Repository Intelligence System",
    add_completion=False,
)

# Session commands
app.command(name="new-session")(session.new_session)
app.command(name="list-sessions")(session.list_sessions)

# Other commands
app.command()(init.init)
app.command()(review.review)
app.command()(add_repo.add_repo)

if __name__ == "__main__":
    app()