import typer
from rich.console import Console
from rich.panel import Panel
from rich.markdown import Markdown
from github import Github
import os
from dataclasses import dataclass, field
from typing import List, Optional

from config import settings
from core.state import ReviewState
from core.graph import review_graph
from core.knowledge_base import KnowledgeBase
from core.memory.manager import MemoryManager
from core.utils import handle_error
from core.observability import get_logger, get_langfuse_client
from core.agents import context_summarizer

logger = get_logger()

console = Console()
memory = MemoryManager()


@dataclass
class PipelineContext:
    repo: str = ""
    number: int = 0
    pr: Optional[object] = None
    raw_context: str = ""
    previous_reviews: List[dict] = field(default_factory=list)
    files_changed: List[str] = field(default_factory=list)
    full_diff: str = ""
    state: Optional[ReviewState] = None
    final_state: Optional[dict] = None


class ReviewPipeline:
    def __init__(self):
        self.context = PipelineContext()

    def run(self, repo: str, number: int, dry_run: bool, verbose: bool):
        try:
            self.context.repo = repo
            self.context.number = number

            conversation_id = get_current_session()

            console.print(Panel.fit(
                f"[bold cyan]CodeTurtle[/bold cyan]\n"
                f"Session: {conversation_id}\n"
                f"Repository: {repo}#{number}\n"
                f"Model: {settings.ollama_model} (Ollama)"
            ))

            self._load_knowledge_base()
            self._fetch_pr()
            self._retrieve_context()
            self._load_previous_reviews(conversation_id)
            self._build_full_diff()
            self._create_review_state()
            self._run_context_summarizer()
            self._run_agent_swarm()
            self._add_langfuse_metadata(conversation_id)
            self._display_results()
            self._save_to_memory(conversation_id)

            if not dry_run:
                console.print("[red]Auto-posting to GitHub is not implemented yet.[/red]")
            else:
                console.print("[dim]--dry-run mode[/dim]")

        except Exception as e:
            handle_error(e, verbose=verbose)

    def _load_knowledge_base(self):
        collection_name = self.context.repo.replace("/", "_")
        self.kb = KnowledgeBase(collection_name=collection_name)

    def _fetch_pr(self):
        g = Github(settings.github_token)
        repo_obj = g.get_repo(self.context.repo)
        self.context.pr = repo_obj.get_pull(self.context.number)

    def _retrieve_context(self):
        query = f"{self.context.pr.title}\n{self.context.pr.body or ''}"
        retrieved_docs = self.kb.similarity_search(query, k=4)
        self.context.raw_context = "\n\n".join(
            [doc.page_content[:1200] for doc in retrieved_docs]
        )
        console.print(f"[yellow]Retrieved {len(retrieved_docs)} relevant chunks from knowledge base[/yellow]")

    def _load_previous_reviews(self, conversation_id: str):
        self.context.previous_reviews = memory.get_recent_reviews(
            conversation_id, self.context.repo, limit=2
        )
        if self.context.previous_reviews:
            console.print(
                f"[yellow]Loaded {len(self.context.previous_reviews)} previous reviews from memory[/yellow]"
            )

    def _build_full_diff(self):
        files = self.context.pr.get_files()
        self.context.files_changed = [f.filename for f in files]
        full_diff = ""
        for f in files:
            if f.patch:
                full_diff += f"--- {f.filename}\n+++ {f.filename}\n{f.patch}\n\n"
        self.context.full_diff = full_diff

    def _create_review_state(self):
        self.context.state = ReviewState(
            repo=self.context.repo,
            number=self.context.number,
            title=self.context.pr.title,
            body=self.context.pr.body or "",
            author=self.context.pr.user.login,
            diff=self.context.full_diff[:8000] if self.context.full_diff else None,
            full_diff=self.context.full_diff,
            files_changed=self.context.files_changed,
            model_used=settings.ollama_model,
            context_from_kb=self.context.raw_context,
            previous_reviews=self.context.previous_reviews,
        )

    def _run_context_summarizer(self):
        self.context.state = context_summarizer(self.context.state)
        console.print("[yellow]Context summarized successfully[/yellow]")

    def _run_agent_swarm(self):
        console.print("[yellow]Running agent swarm...[/yellow]")
        self.context.final_state = review_graph.invoke(self.context.state)

    def _add_langfuse_metadata(self, conversation_id: str):
        langfuse_client = get_langfuse_client()
        if langfuse_client:
            try:
                langfuse_client.update_current_trace(
                    metadata={
                        "repo": self.context.repo,
                        "pr_number": self.context.number,
                        "model": settings.ollama_model,
                        "session_id": conversation_id,
                    },
                    tags=["review", self.context.repo.split("/")[0]],
                )
            except Exception:
                pass

    def _display_results(self):
        console.print("\n[bold green]=== CONTEXT SUMMARY ===[/bold green]")
        console.print(Markdown(self.context.final_state.get("context_summary", "")))

        console.print("\n[bold green]=== CODE QUALITY ANALYSIS ===[/bold green]")
        console.print(Markdown(self.context.final_state.get("code_analysis", "")))

        console.print("\n[bold green]=== CRITIQUE ===[/bold green]")
        console.print(Markdown(self.context.final_state.get("critique", "")))

        console.print("\n[bold cyan]=== FINAL RECOMMENDATION ===[/bold cyan]")
        console.print(Markdown(self.context.final_state.get("final_comment", "")))

    def _save_to_memory(self, conversation_id: str):
        memory.save_review(
            conversation_id=conversation_id,
            repo_name=self.context.repo,
            review_type="pr",
            number=self.context.number,
            title=self.context.state.title,
            recommendation=self.context.final_state.get("recommendation", "N/A"),
            summary=self.context.final_state.get("final_comment", "")[:600]
        )


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

    pipeline = ReviewPipeline()
    pipeline.run(repo, number, dry_run, verbose)