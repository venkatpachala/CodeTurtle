import typer
from rich.console import Console
from rich.panel import Panel
from rich.markdown import Markdown
from github import Github

from config import settings
from core.state import ReviewState
from core.graph import review_graph
from core.knowledge_base import KnowledgeBase

console = Console()

def review(
    repo: str = typer.Argument(..., help="Repository in format owner/repo"),
    number: int = typer.Argument(..., help="PR number"),
    dry_run: bool = typer.Option(True, "--dry-run"),
):
    """Review a PR using the repository knowledge base + agent swarm"""

    console.print(Panel.fit(
        f"[bold cyan]ReviewForge Swarm[/bold cyan]\n"
        f"Repository: {repo}#{number}\n"
        f"Model: {settings.ollama_model} (Ollama)"
    ))

    try:
        # 1. Load Knowledge Base for this repo
        collection_name = repo.replace("/", "_")
        kb = KnowledgeBase(collection_name=collection_name)

        # 2. Fetch PR from GitHub
        g = Github(settings.github_token)
        repo_obj = g.get_repo(repo)
        pr = repo_obj.get_pull(number)

        # 3. Retrieve relevant context from Knowledge Base
        query = f"{pr.title}\n{pr.body or ''}"
        retrieved_docs = kb.similarity_search(query, k=6)
        context_from_kb = "\n\n".join([doc.page_content for doc in retrieved_docs])

        console.print(f"[yellow]Retrieved {len(retrieved_docs)} relevant chunks from knowledge base...[/yellow]")

        # 4. Create initial state with knowledge base context
        state = ReviewState(
            repo=repo,
            number=number,
            title=pr.title,
            body=pr.body or "",
            author=pr.user.login,
            diff=pr.get_files()[0].patch if pr.get_files() else None,
            files_changed=[f.filename for f in pr.get_files()],
            model_used=settings.ollama_model,
        )

        # Store knowledge base context in state (we'll use it in agents)
        state.context_from_kb = context_from_kb

        console.print("[yellow]Running agent swarm with repository knowledge...[/yellow]")

        # 5. Run the LangGraph
        final_state = review_graph.invoke(state)

        # 6. Display results
        console.print("\n[bold green]=== CONTEXT SUMMARY ===[/bold green]")
        console.print(Markdown(final_state["context_summary"]))

        console.print("\n[bold green]=== CODE QUALITY ANALYSIS ===[/bold green]")
        console.print(Markdown(final_state["code_analysis"]))

        console.print("\n[bold green]=== CRITIQUE ===[/bold green]")
        console.print(Markdown(final_state.get("critique", "No critique available")))

        console.print("\n[bold cyan]=== FINAL RECOMMENDATION & COMMENT ===[/bold cyan]")
        console.print(Markdown(final_state.get("final_comment", "No final comment generated")))

        if not dry_run:
            console.print("[red]Posting comment to GitHub is not implemented yet.[/red]")
        else:
            console.print("[dim]--dry-run mode[/dim]")

    except Exception as e:
        console.print(f"[red]Error:[/red] {str(e)}")
        console.print("Make sure the repository was added using `add-repo` command first.")