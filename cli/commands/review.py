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
from core.utils import handle_error
from core.observability import get_logger
from core.observability import get_langfuse_client

logger = get_logger()

# At the beginning of review function


console = Console()
memory = MemoryManager()


def get_current_session() -> str:
    if not os.path.exists(".current_session"):
        raise Exception("No active session found")
    with open(".current_session", "r") as f:
        return f.read().strip()



def review(
    repo: str = typer.Argument(..., help="Repository in format owner/repo"),
    number: int = typer.Argument(..., help="PR number"),
    dry_run: bool = typer.Option(True, "--dry-run"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Show detailed error information"),
):
    logger.info("Starting review", repo=repo, pr_number=number)
    """Review a PR using knowledge base + agent swarm (with memory)"""

    try:
        conversation_id = get_current_session()

        console.print(Panel.fit(
            f"[bold cyan]CodeTurtle[/bold cyan]\n"
            f"Session: {conversation_id}\n"
            f"Repository: {repo}#{number}\n"
            f"Model: {settings.ollama_model} (Ollama)"
        ))

        # Load Knowledge Base
        collection_name = repo.replace("/", "_")
        kb = KnowledgeBase(collection_name=collection_name)

        # Fetch PR
        g = Github(settings.github_token)
        repo_obj = g.get_repo(repo)
        pr = repo_obj.get_pull(number)

        # Retrieve context from Knowledge Base
        query = f"{pr.title}\n{pr.body or ''}"
        retrieved_docs = kb.similarity_search(query, k=6)
        context_from_kb = "\n\n".join([doc.page_content for doc in retrieved_docs])

        console.print(f"[yellow]Retrieved {len(retrieved_docs)} relevant chunks from knowledge base[/yellow]")

        # Fetch previous reviews from memory
        previous_reviews = memory.get_recent_reviews(conversation_id, repo, limit=4)
        if previous_reviews:
            console.print(f"[yellow]Loaded {len(previous_reviews)} previous reviews from memory[/yellow]")

        # Create state
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

        # Run agent swarm
        console.print("[yellow]Running agent swarm...[/yellow]")
        final_state = review_graph.invoke(state)

        # Add custom metadata/tags to Langfuse trace

        langfuse_client = get_langfuse_client()
        if langfuse_client:
            try:
                langfuse_client.update_current_trace(
                metadata={
                "repo": repo,
                "pr_number": number,
                "model": settings.ollama_model,
                "session_id": conversation_id,
            },
            tags=["review", repo.split("/")[0]],   # Example: ["review", "FalkorDB"]
        )
            except Exception:
                pass  # Fail silently if Langfuse update fails

        # Display results
        console.print("\n[bold green]=== CONTEXT SUMMARY ===[/bold green]")
        console.print(Markdown(final_state.get("context_summary", "")))

        console.print("\n[bold green]=== CODE QUALITY ANALYSIS ===[/bold green]")
        console.print(Markdown(final_state.get("code_analysis", "")))

        console.print("\n[bold green]=== CRITIQUE ===[/bold green]")
        console.print(Markdown(final_state.get("critique", "")))

        console.print("\n[bold cyan]=== FINAL RECOMMENDATION ===[/bold cyan]")
        console.print(Markdown(final_state.get("final_comment", "")))

        # Auto-save review to memory
        memory.save_review(
            conversation_id=conversation_id,
            repo_name=repo,
            review_type="pr",
            number=number,
            title=pr.title,
            recommendation=final_state.get("recommendation", "N/A"),
            summary=final_state.get("final_comment", "")[:600]
        )

        if not dry_run:
            console.print("[red]Auto-posting to GitHub is not implemented yet.[/red]")
        else:
            console.print("[dim]--dry-run mode[/dim]")

    except Exception as e:
        handle_error(e, verbose=verbose)

        