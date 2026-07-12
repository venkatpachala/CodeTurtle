import typer
from rich.console import Console
from rich.panel import Panel
from rich.markdown import Markdown
from github import Github
import os

from config import settings
from core.state import ReviewState
from core.graph import review_graph
from core.knowledge_base import KnowledgeBase
from core.memory.manager import MemoryManager

console = Console()
memory = MemoryManager()


def get_current_session() -> str:
    """Get the current active session ID"""
    if not os.path.exists(".current_session"):
        console.print("[red]No active session found![/red]")
        console.print("Please start a session first using: [bold]codeturtle new-session[/bold]")
        raise typer.Exit()
    
    with open(".current_session", "r") as f:
        return f.read().strip()


def review(
    repo: str = typer.Argument(..., help="Repository in format owner/repo"),
    number: int = typer.Argument(..., help="PR number"),
    dry_run: bool = typer.Option(True, "--dry-run"),
):
    """Review a PR inside the current session with memory + knowledge base"""

    conversation_id = get_current_session()

    console.print(Panel.fit(
        f"[bold cyan]CodeTurtle[/bold cyan]\n"
        f"Session: {conversation_id}\n"
        f"Repository: {repo}#{number}\n"
        f"Model: {settings.ollama_model} (Ollama)"
    ))

    try:
        # 1. Load Knowledge Base
        collection_name = repo.replace("/", "_")
        kb = KnowledgeBase(collection_name=collection_name)

        # 2. Fetch PR
        g = Github(settings.github_token)
        repo_obj = g.get_repo(repo)
        pr = repo_obj.get_pull(number)

        # 3. Retrieve context from Knowledge Base
        query = f"{pr.title}\n{pr.body or ''}"
        retrieved_docs = kb.similarity_search(query, k=6)
        context_from_kb = "\n\n".join([doc.page_content for doc in retrieved_docs])

        console.print(f"[yellow]Retrieved {len(retrieved_docs)} relevant chunks from knowledge base[/yellow]")

        # Fetch previous reviews from memory (for context)
        previous_reviews = memory.get_recent_reviews(
            conversation_id=conversation_id,
            repo_name=repo,
            limit=4
        )

        console.print(f"[yellow]Loaded {len(previous_reviews)} previous reviews from memory[/yellow]")

        # 4. Create state
        state = ReviewState(
            repo=repo,
            number=number,
            title=pr.title,
            body=pr.body or "",
            author=pr.user.login,
            diff=pr.get_files()[0].patch if pr.get_files() else None,
            files_changed=[f.filename for f in pr.get_files()],
            model_used=settings.ollama_model,
            context_from_kb=context_from_kb,
            previous_reviews=previous_reviews
        )

        # 5. Run agent swarm
        console.print("[yellow]Running agent swarm...[/yellow]")
        final_state = review_graph.invoke(state)

        # 6. Display results
        console.print("\n[bold green]=== CONTEXT SUMMARY ===[/bold green]")
        console.print(Markdown(final_state.get("context_summary", "")))

        console.print("\n[bold green]=== CODE QUALITY ANALYSIS ===[/bold green]")
        console.print(Markdown(final_state.get("code_analysis", "")))

        console.print("\n[bold green]=== CRITIQUE ===[/bold green]")
        console.print(Markdown(final_state.get("critique", "")))

        console.print("\n[bold cyan]=== FINAL RECOMMENDATION ===[/bold cyan]")
        console.print(Markdown(final_state.get("final_comment", "")))

        # 7. Save review to memory automatically
        memory.save_review(
            conversation_id=conversation_id,
            repo_name=repo,
            review_type="pr",
            number=number,
            title=pr.title,
            recommendation=final_state.get("recommendation", "N/A"),
            summary=final_state.get("final_comment", "")[:500]   # Save first 500 chars
        )

        if not dry_run:
            console.print("[red]Auto-posting to GitHub not implemented yet.[/red]")
        else:
            console.print("[dim]--dry-run mode[/dim]")

    except Exception as e:
        console.print(f"[red]Error:[/red] {str(e)}")