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
from core.observability import get_logger, get_langfuse_client
from core.agents import context_summarizer

logger = get_logger()

console = Console()
memory = MemoryManager()


def get_current_session() -> str:
    if not os.path.exists(".current_session"):
        raise Exception("No active session found")
    with open(".current_session", "r") as f:
        return f.read().strip()


class ReviewPipeline:
    """Clean orchestration for the full review process"""

    def __init__(self):
        self.kb = None
        self.pr = None
        self.state = None

    def run(self, repo: str, number: int, dry_run: bool, verbose: bool):
        try:
            conversation_id = get_current_session()

            console.print(Panel.fit(
                f"[bold cyan]CodeTurtle[/bold cyan]\n"
                f"Session: {conversation_id}\n"
                f"Repository: {repo}#{number}\n"
                f"Model: {settings.ollama_model} (Ollama)"
            ))

            # 1. Load Knowledge Base + Retrieve Context
            self._load_knowledge_base(repo)

            # 2. Fetch PR from GitHub
            self._fetch_pr(repo, number)

            # 3. Summarize context
            self._summarize_context()

            # 4. Load previous reviews from memory
            self._load_previous_reviews(conversation_id, repo)

            # 5. Build multi-file diff
            self._build_full_diff()

            # 6. Create ReviewState
            self._create_review_state(conversation_id)

            # 7. Run agent swarm
            self._run_agent_swarm()

            # 8. Add metadata to Langfuse
            self._add_langfuse_metadata(repo, number, conversation_id)

            # 9. Display results
            self._display_results()

            # 10. Save to memory
            self._save_to_memory(conversation_id, repo)

            if not dry_run:
                console.print("[red]Auto-posting to GitHub is not implemented yet.[/red]")
            else:
                console.print("[dim]--dry-run mode[/dim]")

        except Exception as e:
            handle_error(e, verbose=verbose)

    def _load_knowledge_base(self, repo: str):
        collection_name = repo.replace("/", "_")
        self.kb = KnowledgeBase(collection_name=collection_name)

    def _fetch_pr(self, repo: str, number: int):
        g = Github(settings.github_token)
        repo_obj = g.get_repo(repo)
        self.pr = repo_obj.get_pull(number)

    def _summarize_context(self):
        query = f"{self.pr.title}\n{self.pr.body or ''}"
        retrieved_docs = self.kb.similarity_search(query, k=4)
        raw_context = "\n\n".join([doc.page_content[:1200] for doc in retrieved_docs])

        temp_state = ReviewState(title=self.pr.title, context_from_kb=raw_context)
        summarized_state = context_summarizer(temp_state)
        self.state = ReviewState(  # We'll build full state later
            title=self.pr.title,
            context_from_kb=summarized_state.summarized_context,
            summarized_context=summarized_state.summarized_context
        )
        console.print("[yellow]Context summarized successfully[/yellow]")

    def _load_previous_reviews(self, conversation_id: str, repo: str):
        self.state.previous_reviews = memory.get_recent_reviews(conversation_id, repo, limit=2)
        if self.state.previous_reviews:
            console.print(f"[yellow]Loaded {len(self.state.previous_reviews)} previous reviews from memory[/yellow]")

    def _build_full_diff(self):
        files = self.pr.get_files()
        self.state.files_changed = [f.filename for f in files]
        full_diff = ""
        for f in files:
            if f.patch:
                full_diff += f"--- {f.filename}\n+++ {f.filename}\n{f.patch}\n\n"
        self.state.full_diff = full_diff
        self.state.diff = full_diff[:8000] if full_diff else None

    def _create_review_state(self, conversation_id: str):
        self.state.repo = repo  # from outer scope - fix in full integration
        self.state.number = number
        self.state.author = self.pr.user.login
        self.state.model_used = settings.ollama_model

    def _run_agent_swarm(self):
        console.print("[yellow]Running agent swarm...[/yellow]")
        self.final_state = review_graph.invoke(self.state)

    def _add_langfuse_metadata(self, repo: str, number: int, conversation_id: str):
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
                    tags=["review", repo.split("/")[0]],
                )
            except Exception:
                pass

    def _display_results(self):
        console.print("\n[bold green]=== CONTEXT SUMMARY ===[/bold green]")
        console.print(Markdown(self.final_state.get("context_summary", "")))

        console.print("\n[bold green]=== CODE QUALITY ANALYSIS ===[/bold green]")
        console.print(Markdown(self.final_state.get("code_analysis", "")))

        console.print("\n[bold green]=== CRITIQUE ===[/bold green]")
        console.print(Markdown(self.final_state.get("critique", "")))

        console.print("\n[bold cyan]=== FINAL RECOMMENDATION ===[/bold cyan]")
        console.print(Markdown(self.final_state.get("final_comment", "")))

    def _save_to_memory(self, conversation_id: str, repo: str):
        memory.save_review(
            conversation_id=conversation_id,
            repo_name=repo,
            review_type="pr",
            number=self.state.number,
            title=self.state.title,
            recommendation=self.final_state.get("recommendation", "N/A"),
            summary=self.final_state.get("final_comment", "")[:600]
        )