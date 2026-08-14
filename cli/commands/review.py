import os
from dataclasses import dataclass, field
from typing import Any, List, Optional

import typer
from github import Github
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel

from config import settings
from core.graph import review_graph
from core.knowledge_base import KnowledgeBase
from core.memory.manager import MemoryManager
from core.observability import get_langfuse_client, get_logger
from core.query_engine import RepositoryQueryEngine
from core.utils import handle_error

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
    engine: Optional[object] = None
    files_changed: List[str] = field(default_factory=list)
    full_diff: str = ""
    state: Optional[dict] = None
    final_state: Optional[dict] = None


def get_current_session() -> str:
    if not os.path.exists(".current_session"):
        raise Exception("No active session found. Run: python -m cli.main new-session")
    with open(".current_session", "r") as f:
        return f.read().strip()


def _as_dict(obj: Any) -> dict:
    if obj is None:
        return {}
    if isinstance(obj, dict):
        return obj
    if hasattr(obj, "model_dump"):
        return obj.model_dump()
    return {}


def _finding_line(finding: Any) -> dict:
    d = _as_dict(finding)
    if d:
        return d
    return {
        "title": getattr(finding, "title", str(finding)),
        "severity": getattr(finding, "severity", "?"),
        "confidence": getattr(finding, "confidence", 0),
        "evidence": getattr(finding, "evidence", []),
        "reasoning": getattr(finding, "reasoning", ""),
        "recommendation": getattr(finding, "recommendation", ""),
        "category": getattr(finding, "category", ""),
    }


class ReviewPipeline:
    """CLI orchestration: GitHub + KB setup, then LangGraph owns the review."""

    def __init__(self):
        self.context = PipelineContext()

    def run(self, repo: str, number: int, dry_run: bool, verbose: bool):
        try:
            self.context.repo = repo
            self.context.number = number
            self.context.conversation_id = get_current_session()

            console.print(
                Panel.fit(
                    f"[bold cyan]CodeTurtle[/bold cyan]\n"
                    f"Session: {self.context.conversation_id}\n"
                    f"Repository: {repo}#{number}\n"
                    f"Model: {settings.ollama_model} (Ollama)"
                )
            )

            self._load_knowledge_base()
            self._fetch_pr()
            self._build_full_diff()
            self._create_review_state()

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
        self.context.engine = RepositoryQueryEngine(
            self.context.repo,
            kb=self.context.kb,
        )

    def _fetch_pr(self):
        g = Github(settings.github_token)
        repo_obj = g.get_repo(self.context.repo)
        self.context.pr = repo_obj.get_pull(self.context.number)

    def _build_full_diff(self):
        files = list(self.context.pr.get_files())
        self.context.files_changed = [f.filename for f in files]
        parts = []
        for f in files:
            if f.patch:
                parts.append(f"--- {f.filename}\n+++ {f.filename}\n{f.patch}\n")
        self.context.full_diff = "\n".join(parts)

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
            "kb": self.context.kb,
            "engine": self.context.engine,
            "context_from_kb": "",
            "traces": [],
        }

    def _add_langfuse_metadata(self):
        langfuse_client = get_langfuse_client()
        if not langfuse_client:
            return
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
        final = self.context.final_state or {}

        # ── PR Understanding ─────────────────────────────────────────────
        understanding = _as_dict(final.get("pr_understanding"))
        if understanding:
            console.print("\n[bold cyan]=== PR UNDERSTANDING ===[/bold cyan]")
            console.print(f"**Summary**: {understanding.get('summary', '')}")
            console.print(f"**Risk Level**: {understanding.get('risk_level', '')}")
            change_types = (
                understanding.get("change_type")
                or understanding.get("change_types")
                or []
            )
            if isinstance(change_types, list):
                console.print(
                    f"**Change Types**: {', '.join(str(x) for x in change_types)}"
                )
            console.print(
                f"**Focus Areas**: {', '.join(str(x) for x in (understanding.get('focus_areas') or []))}"
            )

        # ── Review Plan ──────────────────────────────────────────────────
        plan = _as_dict(final.get("review_plan"))
        if plan:
            console.print("\n[bold magenta]=== REVIEW PLAN ===[/bold magenta]")
            reviewers = plan.get("reviewers") or []
            console.print(f"**Reviewers**: {', '.join(str(r) for r in reviewers)}")
            console.print(f"**Risk**: {plan.get('risk_level', '')}")
            qs = plan.get("retrieval_questions") or []
            console.print(f"**Retrieval questions**: {len(qs)}")
            for q in qs[:8]:
                if isinstance(q, dict):
                    console.print(
                        f"  - [{q.get('purpose', '')}] {str(q.get('question', ''))[:100]}"
                    )
                else:
                    console.print(f"  - {q}")

        # ── Specialists (always show meta: raw / grounded / skipped) ─────
        console.print("\n[bold red]=== CORRECTNESS ===[/bold red]")
        self._print_meta(
            "CORRECTNESS",
            final.get("correctness_meta"),
            final.get("correctness_findings") or [],
        )

        console.print("\n[bold yellow]=== CODE QUALITY ===[/bold yellow]")
        self._print_meta(
            "CODE QUALITY",
            final.get("quality_meta"),
            final.get("quality_findings") or [],
        )

        console.print("\n[bold blue]=== TESTING ===[/bold blue]")
        self._print_meta(
            "TESTING",
            final.get("testing_meta"),
            final.get("testing_findings") or [],
        )

        # Legacy fallback if only old code_analysis present
        if (
            not (final.get("correctness_findings") or final.get("quality_findings"))
            and final.get("code_analysis")
        ):
            console.print("\n[bold green]=== CODE QUALITY ANALYSIS (legacy) ===[/bold green]")
            console.print(str(final.get("code_analysis"))[:2000])

        # ── Critic ───────────────────────────────────────────────────────
        critique = _as_dict(final.get("critique"))
        kept = final.get("findings") or critique.get("kept") or []
        console.print("\n[bold green]=== CRITIQUE ===[/bold green]")
        if critique.get("notes"):
            console.print(f"[dim]{critique.get('notes')}[/dim]")
        dropped = critique.get("dropped") or []
        if dropped:
            console.print("[dim]Dropped:[/dim]")
            for d in dropped[:15]:
                if isinstance(d, dict):
                    console.print(f"  - {d.get('title', d)} ({d.get('reason', '')})")
                else:
                    console.print(f"  - {d}")
        if kept:
            console.print("[bold]Kept findings:[/bold]")
            self._print_findings(kept)
        else:
            console.print("No findings kept after critic.")

        # ── Final decision ───────────────────────────────────────────────
        rec = final.get("recommendation") or _as_dict(final.get("merge_decision")).get(
            "recommendation", "N/A"
        )
        console.print("\n[bold cyan]=== FINAL RECOMMENDATION ===[/bold cyan]")
        console.print(f"[bold]Decision: {rec}[/bold]")
        final_comment = final.get("final_comment", "")
        if final_comment:
            console.print(Markdown(str(final_comment)))

    def _print_findings(self, findings: list):
        for finding in findings:
            d = _finding_line(finding)
            title = d.get("title", "?")
            sev = d.get("severity", "?")
            conf = d.get("confidence", 0)
            try:
                conf_s = f"{float(conf):.2f}"
            except Exception:
                conf_s = str(conf)
            console.print(f"**{title}** ({sev}) — confidence {conf_s}")
            console.print(f"Evidence: {d.get('evidence') or []}")
            reasoning = d.get("reasoning") or d.get("description") or ""
            if reasoning:
                console.print(f"Reasoning: {reasoning}")
            if d.get("recommendation"):
                console.print(f"Recommendation: {d.get('recommendation')}")
            console.print("---")

    def _print_meta(self, label: str, meta: Any, findings: list):
        meta = meta if isinstance(meta, dict) else {}
        if meta.get("skipped"):
            console.print(f"[dim]{label}: skipped (not in plan)[/dim]")
            return
        raw = meta.get("raw", "?")
        grounded = meta.get("grounded", len(findings) if findings is not None else 0)
        extra = ""
        if "no_issues_in_diff" in meta:
            extra = f" no_issues_in_diff={meta.get('no_issues_in_diff')}"
        if "tests_touched" in meta:
            extra += f" tests_touched={meta.get('tests_touched')}"
        console.print(f"[dim]{label}: raw={raw} grounded={grounded}{extra}[/dim]")
        if findings:
            self._print_findings(findings)
        else:
            console.print(f"[dim]{label}: no grounded findings[/dim]")

    def _save_to_memory(self):
        final = self.context.final_state or {}
        memory.save_review(
            conversation_id=self.context.conversation_id,
            repo_name=self.context.repo,
            review_type="pr",
            number=self.context.number,
            title=(self.context.state or {}).get("title", ""),
            recommendation=final.get("recommendation", "N/A"),
            summary=str(final.get("final_comment", ""))[:600],
        )


def review(
    repo: str = typer.Argument(..., help="Repository in format owner/repo"),
    number: int = typer.Argument(..., help="PR number"),
    dry_run: bool = typer.Option(True, "--dry-run"),
    verbose: bool = typer.Option(
        False, "--verbose", "-v", help="Show detailed error information"
    ),
):
    logger.info("Starting review", repo=repo, pr_number=number)
    ReviewPipeline().run(repo, number, dry_run, verbose)
      