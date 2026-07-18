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

logger = get_logger()

console = Console()
memory = MemoryManager()


@dataclass
class PipelineContext:
    repo: str = ""
    number: int = 0
    conversation_id: str = ""
    pr: Optional[object] = None
    kb: Optional[object] = None
    files_changed: List[str] = field(default_factory=list)
    full_diff: str = ""
    state: Optional[dict] = None
    final_state: Optional[dict] = None


class ReviewPipeline:
    """Clean orchestration for the full review process"""

    def __init__(self):
        self.context = PipelineContext()

    def run(self, repo: str, number: int, dry_run: bool, verbose: bool):
        try:
            self.context.repo = repo
            self.context.number = number
            self.context.conversation_id = get_current_session()

            console.print(Panel.fit(
                f"[bold cyan]CodeTurtle[/bold cyan]\n"
                f"Session: {self.context.conversation_id}\n"
                f"Repository: {repo}#{number}\n"
                f"Model: {settings.ollama_model} (Ollama)"
            ))

            # Only deterministic steps in CLI
            self._load_knowledge_base()
            self._fetch_pr()
            self._build_full_diff()
            self._create_review_state()

            # Single entry point into LangGraph (the real orchestrator)
            console.print("[yellow]Running agent swarm...[/yellow]")
            self.context.final_state = review_graph.invoke(self.context.state)

            self._add_langfuse_metadata()
            self._display_results()
            self._save_to_memory()

            if not dry_run:
                console.print("[red]Auto-posting to GitHub is not implemented yet.[/red]")
            else:
                console.print("[dim]--dry-run mode[/dim]")

        except Exception as e:
            handle_error(e, verbose=verbose)

    def _load_knowledge_base(self):
        collection_name = self.context.repo.replace("/", "_")
        self.context.kb = KnowledgeBase(collection_name)

    def _fetch_pr(self):
        g = Github(settings.github_token)
        repo_obj = g.get_repo(self.context.repo)
        self.context.pr = repo_obj.get_pull(self.context.number)

    def _build_full_diff(self):
        files = self.context.pr.get_files()
        self.context.files_changed = [f.filename for f in files]
        full_diff = ""
        for f in files:
            if f.patch:
                full_diff += f"--- {f.filename}\n+++ {f.filename}\n{f.patch}\n\n"
        self.context.full_diff = full_diff

    def _create_review_state(self):
        self.context.state = {
            "repo": self.context.repo,
            "number": self.context.number,
            "title": self.context.pr.title,
            "body": self.context.pr.body or "",
            "author": self.context.pr.user.login,
            "full_diff": self.context.full_diff,
            "files_changed": self.context.files_changed,
            "model_used": settings.ollama_model,
            "context_from_kb": "",
            "traces": [],
        }

    def _add_langfuse_metadata(self):
        langfuse_client = get_langfuse_client()
        if langfuse_client:
            try:
                langfuse_client.update_current_trace(
                    metadata={
                        "repo": self.context.repo,
                        "pr_number": self.context.number,
                        "model": settings.ollama_model,
                        "session_id": self.context.conversation_id,
                    },
                    tags=["review", self.context.repo.split("/")[0]],
                )
            except Exception:
                pass

    def _display_results(self):
        # Display PR Understanding first
        understanding = self.context.final_state.get("pr_understanding", {})
        if understanding:
            console.print("\n[bold cyan]=== PR UNDERSTANDING ===[/bold cyan]")
            console.print(f"**Summary**: {understanding.get('summary', '')}")
            console.print(f"**Risk Level**: {understanding.get('risk_level', '')}")
            console.print(f"**Change Types**: {', '.join(understanding.get('change_type', []))}")
            console.print(f"**Focus Areas**: {', '.join(understanding.get('focus_areas', []))}")

        # Display Correctness Findings
        findings = self.context.final_state.get("findings", [])
        if findings:
            console.print("\n[bold red]=== CORRECTNESS FINDINGS ===[/bold red]")
            for finding in findings:
                console.print(f"**{finding.title}** ({finding.severity})")
                console.print(f"Evidence: {finding.evidence}")
                console.print(f"Recommendation: {finding.recommendation}")
                console.print("---")

        # Rest of the display
        final = self.context.final_state or {}
        console.print("\n[bold green]=== CONTEXT SUMMARY ===[/bold green]")
        console.print(Markdown(final.get("context_summary", "")))

        console.print("\n[bold green]=== CODE QUALITY ANALYSIS ===[/bold green]")
        code_analysis = final.get("code_analysis", {})
        if isinstance(code_analysis, dict):
            analysis_text = f"**Summary**: {code_analysis.get('summary', '')}\n**Recommendation**: {code_analysis.get('recommendation', '')}"
        else:
            analysis_text = str(code_analysis)
        console.print(Markdown(analysis_text))

        console.print("\n[bold green]=== CRITIQUE ===[/bold green]")
        critique = final.get("critique", {})
        if isinstance(critique, dict):
            critique_text = f"**Summary**: {critique.get('summary', '')}\n**Recommendation**: {critique.get('recommendation', '')}"
        else:
            critique_text = str(critique)
        console.print(Markdown(critique_text))

        console.print("\n[bold cyan]=== FINAL RECOMMENDATION ===[/bold cyan]")
        final_comment = final.get("final_comment", "")
        console.print(Markdown(str(final_comment)))

    def _save_to_memory(self):
        memory.save_review(
            conversation_id=self.context.conversation_id,
            repo_name=self.context.repo,
            review_type="pr",
            number=self.context.number,
            title=self.context.state.get("title", ""),
            recommendation=self.context.final_state.get("recommendation", "N/A"),
            summary=self.context.final_state.get("final_comment", "")[:600]
        )


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