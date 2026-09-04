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
from core.graphify_retriever import GraphifyRetriever
from core.knowledge_base import KnowledgeBase
from core.memory.manager import MemoryManager
from core.observability import get_langfuse_client, get_logger
from core.query_engine import RepositoryQueryEngine
from core.utils import handle_error

logger = get_logger()
console = Console()
memory = MemoryManager()


class _SkipReview(Exception):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


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
    raw_context: str = ""
    pr_facts: Optional[dict] = None
    state: Optional[dict] = None
    final_state: Optional[dict] = None
    execute_tests: bool = False
    execute_install: bool = False
    pr_head_sha: str = ""
    config_path: str = ""
    repo_cfg: Optional[object] = None
    change_units_payload: Optional[dict] = None


def get_current_session() -> str:
    from core.ci import ensure_session

    return ensure_session()


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
        "file": getattr(finding, "file", None),
        "symbol": getattr(finding, "symbol", None),
        "reasoning": getattr(finding, "reasoning", ""),
        "recommendation": getattr(finding, "recommendation", ""),
        "category": getattr(finding, "category", ""),
    }


class ReviewPipeline:
    """CLI orchestration: GitHub + KB setup, then LangGraph owns the review."""

    last_snapshot = None

    def __init__(self):
        self.context = PipelineContext()

    def run(
        self,
        repo: str,
        number: int,
        dry_run: bool,
        verbose: bool,
        execute_tests: bool = False,
        execute_install: bool = False,
        comment: bool = False,
        config_path: str = "",
    ):
        try:
            from core.repo_config import (
                RepoConfigError,
                find_config_path,
                load_repo_config,
                merge_review_config,
            )

            self.context.repo = repo
            self.context.number = number
            self.context.config_path = config_path or ""

            try:
                cfg_path = find_config_path(config_path or None)
                repo_yaml = load_repo_config(cfg_path)
            except RepoConfigError as exc:
                console.print(f"[red]{exc}[/red]")
                raise SystemExit(1) from exc

            cfg = merge_review_config(
                repo=repo_yaml,
                cli_execute_tests=bool(execute_tests),
                cli_execute_install=bool(execute_install),
                settings=settings,
                config_path=cfg_path,
            )
            self.context.repo_cfg = cfg
            self.context.execute_tests = bool(cfg.execute_tests)
            self.context.execute_install = bool(cfg.execute_install)
            if cfg.model:
                settings.ollama_model = cfg.model
            if cfg.llm_backend:
                settings.llm_backend = cfg.llm_backend
            if cfg_path:
                print(f"[Review] config={cfg_path}")

            from core.ci import should_skip_pr_review

            if os.environ.get("GITHUB_ACTIONS"):
                draft = (os.environ.get("CODETURTLE_PR_DRAFT") or "").strip().lower() in (
                    "1",
                    "true",
                    "yes",
                )
                review_drafts = (
                    os.environ.get("CODETURTLE_REVIEW_DRAFTS") or ""
                ).strip().lower() in ("1", "true", "yes")
                skip, why = should_skip_pr_review(
                    actor=os.environ.get("GITHUB_ACTOR") or "",
                    draft=draft,
                    review_drafts=review_drafts,
                )
                if skip:
                    console.print(f"[dim][CI] skip reason={why}[/dim]")
                    return

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
            self._retrieve_context()
            self._create_review_state()

            console.print("[yellow]Running agent swarm...[/yellow]")
            self.context.final_state = review_graph.invoke(self.context.state)
            self._write_eval_snapshot()

            self._add_langfuse_metadata()
            self._display_results()
            self._save_to_memory()

            posted = self._maybe_post(dry_run=dry_run, comment=comment)
            if posted is False:
                raise SystemExit(1)

        except _SkipReview as skip:
            console.print(f"[dim][Review] skip reason={skip.reason}[/dim]")
            return
        except SystemExit:
            raise
        except Exception as e:
            handle_error(e, verbose=verbose)

    def _load_knowledge_base(self):
        # Graphify-only retrieval path
        self.context.kb = None
        self.context.engine = None
        print("[Review] Retrieval backend: Graphify only (Qdrant disabled)")

    def _fetch_pr(self):
        from core.ci import resolve_github_token

        token = resolve_github_token(fallback=str(settings.github_token or ""))
        g = Github(token)
        repo_obj = g.get_repo(self.context.repo)
        self.context.pr = repo_obj.get_pull(self.context.number)
        head = getattr(self.context.pr, "head", None)
        self.context.pr_head_sha = str(getattr(head, "sha", "") or "")
        from core.repo_config import review_skip_reason

        cfg = self.context.repo_cfg
        author = ""
        try:
            author = str(self.context.pr.user.login or "")
        except Exception:
            author = ""
        draft = bool(getattr(self.context.pr, "draft", False))
        why = review_skip_reason(author=author, draft=draft, cfg=cfg) if cfg else None
        if why:
            raise _SkipReview(why)

    def _build_full_diff(self):
        from core.ignore import is_ignored

        files = list(self.context.pr.get_files())
        patterns = []
        cfg = self.context.repo_cfg
        if cfg is not None:
            patterns = list(getattr(cfg, "ignore_paths", None) or [])
        if patterns:
            kept = []
            dropped = []
            for f in files:
                name = (f.filename or "").replace("\\", "/")
                if is_ignored(name, patterns):
                    dropped.append(name)
                else:
                    kept.append(f)
            if dropped:
                print(f"[Review] ignore_paths dropped={dropped[:12]}")
            files = kept
            if not files:
                print("[Review] skip reason=all_files_ignored")
                raise _SkipReview("all_files_ignored")
        self.context.files_changed = [f.filename for f in files]
        parts = []
        for f in files:
            name = (f.filename or "").replace("\\", "/")
            prev = (getattr(f, "previous_filename", None) or name).replace("\\", "/")
            status = (getattr(f, "status", None) or "modified").lower()
            parts.append(f"diff --git a/{prev} b/{name}")
            if status == "added":
                parts.append("--- /dev/null")
                parts.append(f"+++ b/{name}")
            elif status in ("removed", "deleted"):
                parts.append(f"--- a/{prev}")
                parts.append("+++ /dev/null")
            else:
                parts.append(f"--- a/{prev}")
                parts.append(f"+++ b/{name}")
            if f.patch:
                parts.append(f.patch)
            parts.append("")
        self.context.full_diff = "\n".join(parts)

        from core.pr_facts import build_pr_facts
        facts = build_pr_facts(
            title=self.context.pr.title or "",
            body=self.context.pr.body or "",
            files_changed=list(self.context.files_changed or []),
            full_diff=self.context.full_diff or "",
            pr_number=self.context.number,
            repo=self.context.repo,
        )
        self.context.pr_facts = facts

        print(
            f"[PRFacts] files={facts['file_count']} "
            f"classification={facts.get('classification')} "
            f"lock={len(facts.get('lock_files') or [])} "
            f"source={len(facts.get('source_files') or [])} "
            f"diff_bytes={facts['diff_bytes']} "
            f"stat={facts['diff_stat']} "
            f"paths={facts['files_changed'][:10]}"
        )
        self.context.change_units_payload = None
        try:
            from core.change_units import attach_change_units

            payload = attach_change_units(
                {
                    "full_diff": self.context.full_diff or "",
                    "files_changed": list(self.context.files_changed or []),
                    "pr_facts": facts,
                }
            )
            self.context.change_units_payload = payload
        except Exception as exc:
            print(f"[ChangeUnits] attach failed: {type(exc).__name__}")
            self.context.change_units_payload = None

    def _retrieve_context(self):
        retriever = GraphifyRetriever(self.context.repo)

        query = f"""Title:
{self.context.pr.title}

Description:
{self.context.pr.body or ''}
""".strip()

        docs = retriever.retrieve(
            query,
            k=8,
            pr_title=self.context.pr.title or "",
            pr_body=self.context.pr.body or "",
            files_changed=list(self.context.files_changed or []),
            full_diff=self.context.full_diff,
            pr_number=self.context.number,
        )

        self.context.raw_context = "\n\n---\n\n".join(
            d.page_content for d in docs if d.page_content
        )
        print(f"[DEBUG] Graphify-only context chars={len(self.context.raw_context)}")

    def _create_review_state(self):
        self.context.state = {
            "repo": self.context.repo,
            "number": self.context.number,
            "title": self.context.pr.title,
            "body": self.context.pr.body or "",
            "author": self.context.pr.user.login,
            "full_diff": self.context.full_diff,
            "files_changed": self.context.files_changed,
            "pr_facts": self.context.pr_facts or {},
            **dict(getattr(self.context, "change_units_payload", None) or {}),
            "model_used": settings.ollama_model,
            "kb": None,
            "engine": None,
            "context_from_kb": getattr(self.context, "raw_context", ""),
            "traces": [],
            "execute_tests": bool(self.context.execute_tests),
            "execute_install": bool(self.context.execute_install),
            "inline_max": int(getattr(self.context.repo_cfg, "inline_max", 8) or 8),
            "inline_lockfile": bool(getattr(self.context.repo_cfg, "inline_lockfile", False)),
            "coverage_merge_min": float(
                getattr(self.context.repo_cfg, "coverage_merge_min", 0.5) or 0.5
            ),
            "ignore_paths": list(getattr(self.context.repo_cfg, "ignore_paths", None) or []),
            "pr_head_sha": self.context.pr_head_sha or "",
            "execute_timeout_s": int(getattr(settings, "execute_timeout_s", 120)),
            "execute_max_files": int(getattr(settings, "execute_max_files", 8)),
            "execute_install_timeout_s": int(
                getattr(settings, "execute_install_timeout_s", 180)
            ),
            "execute_allow_npm": bool(getattr(settings, "execute_allow_npm", True)),
            "execute_allow_npm_scripts": bool(
                getattr(settings, "execute_allow_npm_scripts", False)
            ),
        }

    def _write_eval_snapshot(self):
        """Always write artifacts/last_review_snapshot.json for run_eval --live."""
        try:
            from core.evaluation.snapshot import write_review_snapshot

            state = dict(self.context.final_state or {})
            if self.context.pr_facts and not state.get("pr_facts"):
                state["pr_facts"] = self.context.pr_facts
            snap = write_review_snapshot(state)
            ReviewPipeline.last_snapshot = snap
        except Exception:
            ReviewPipeline.last_snapshot = None

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
            asks = plan.get("investigate") or []
            if asks:
                console.print(f"**Investigate asks**: {len(asks)}")
                for a in asks[:6]:
                    if isinstance(a, dict):
                        console.print(
                            f"  - {a.get('file')} symbol={a.get('symbol') or ''} ask={a.get('ask')}"
                        )
                    else:
                        console.print(f"  - {a}")

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

        inv = final.get("investigation_report") if isinstance(final.get("investigation_report"), dict) else {}
        if inv:
            console.print("\n[bold cyan]=== INVESTIGATION ===[/bold cyan]")
            if inv.get("skipped"):
                console.print(f"[dim]skipped reason={inv.get('reason')}[/dim]")
            else:
                console.print(
                    f"[dim]hops={inv.get('hops')} calls={inv.get('calls')} "
                    f"hypotheses={inv.get('hypotheses')}[/dim]"
                )
            for h in (final.get("hypotheses") or [])[:6]:
                d = h if isinstance(h, dict) else {}
                console.print(
                    f"  {d.get('id')} status={d.get('status')} file={d.get('file')} "
                    f"evidence={d.get('evidence_ids')}"
                )

        vrep = final.get("verification_report") if isinstance(final.get("verification_report"), dict) else {}
        if vrep:
            console.print("\n[bold cyan]=== VERIFICATION ===[/bold cyan]")
            console.print(
                f"[dim]supported={vrep.get('supported')} "
                f"uncertain={vrep.get('uncertain')} "
                f"unsupported={vrep.get('unsupported')} "
                f"tests_touched={vrep.get('tests_touched')}/{vrep.get('tests_touched_of')} "
                f"suggested={vrep.get('suggested_recommendation')}[/dim]"
            )
            for rec in (vrep.get("records") or [])[:12]:
                if not isinstance(rec, dict):
                    continue
                console.print(
                    f"  {str(rec.get('status') or '').upper()} "
                    f"file={rec.get('file')} "
                    f"reasons={rec.get('reasons')} "
                    f"tokens={rec.get('matched_tokens')}"
                )
                if rec.get("tests_touched") and rec.get("related_tests"):
                    console.print(
                        f"  related: {rec.get('file')} → {rec.get('related_tests')}"
                    )

        ex = final.get("execution_report") if isinstance(final.get("execution_report"), dict) else {}
        if ex:
            console.print("\n[bold cyan]=== EXECUTION ===[/bold cyan]")
            py = ex.get("python") if isinstance(ex.get("python"), dict) else {}
            js = ex.get("js") if isinstance(ex.get("js"), dict) else {}
            if ex.get("python_env") or py.get("env"):
                console.print(
                    f"[dim]python_env={ex.get('python_env') or py.get('env')} "
                    f"frozen={py.get('frozen')} cached={py.get('cached')}[/dim]"
                )
            if ex.get("skipped"):
                console.print(f"[dim]skipped reason={ex.get('skip_reason')}[/dim]")
            else:
                console.print(
                    f"[dim]cmd={ex.get('cmd')} exit={ex.get('exit_code')} "
                    f"elapsed={ex.get('elapsed_s')}s "
                    f"passed={ex.get('passed')} failed={ex.get('failed')}[/dim]"
                )
            if js.get("skip_reason") or js.get("cmd"):
                if js.get("skipped"):
                    console.print(f"[dim]js skip reason={js.get('skip_reason')}[/dim]")
                else:
                    console.print(
                        f"[dim]js_cwd={js.get('cwd')} js_cmd={js.get('cmd')} "
                        f"js_exit={js.get('exit_code')}[/dim]"
                    )

        # ── Critic (validated survivors only) ────────────────────────────
        report = final.get("validation_report") if isinstance(final.get("validation_report"), dict) else {}
        if report:
            console.print(
                f"\n[dim][Grounding] raw={report.get('raw')} "
                f"kept={report.get('kept')} dropped={report.get('dropped')}[/dim]"
            )
        critique = _as_dict(final.get("critique"))
        kept = (
            final.get("validated_findings")
            or final.get("findings")
            or critique.get("kept")
            or []
        )
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
            console.print("no validated findings")

        # ── Coverage (7.3) ──────────────────────────────────────────────
        cov = final.get("review_coverage") if isinstance(final.get("review_coverage"), dict) else {}
        packed = int(cov.get("units_packed") or 0)
        total = int(cov.get("units_total") or 0)
        ratio = final.get("coverage_ratio")
        if ratio is None and total:
            ratio = packed / total
        low = final.get("coverage_low")
        reason = final.get("policy_reason") or _as_dict(final.get("merge_decision")).get(
            "policy_reason", ""
        )
        if cov or ratio is not None or reason:
            console.print("\n[bold cyan]=== COVERAGE ===[/bold cyan]")
            ratio_s = f"{float(ratio):.2f}" if ratio is not None else "?"
            console.print(
                f"units {packed}/{total} ({ratio_s}) low={str(bool(low)).lower()}"
            )
            if reason:
                console.print(f"policy_reason={reason}")

        # ── Final decision ───────────────────────────────────────────────
        rec = final.get("recommendation") or _as_dict(final.get("merge_decision")).get(
            "recommendation", "N/A"
        )
        console.print("\n[bold cyan]=== FINAL RECOMMENDATION ===[/bold cyan]")
        console.print(f"[bold]Decision: {rec}[/bold]")
        if reason:
            console.print(f"[dim]{rec} ({reason})[/dim]")
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
            if d.get("file"):
                console.print(f"File: {d.get('file')}")
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
        grounded = meta.get("validated", meta.get("grounded", len(findings) if findings is not None else 0))
        extra = ""
        if "no_issues_in_diff" in meta:
            extra = f" no_issues_in_diff={meta.get('no_issues_in_diff')}"
        if "tests_touched" in meta:
            extra += f" tests_touched={meta.get('tests_touched')}"
        console.print(f"[dim]{label}: raw={raw} grounded={grounded}{extra}[/dim]")
        if findings:
            self._print_findings(findings)
        else:
            console.print(f"[dim]{label}: no validated findings[/dim]")

    def _maybe_post(self, *, dry_run: bool, comment: bool) -> Optional[bool]:
        """Return True if posted/skipped, False on hard failure, None if dry-run."""
        from core.github_review import post_pull_request_review, should_post

        if not should_post(dry_run=dry_run, comment=comment):
            console.print("[dim]--dry-run mode (not posted)[/dim]")
            return None

        state = dict(self.context.final_state or {})
        if self.context.pr_facts and not state.get("pr_facts"):
            state["pr_facts"] = self.context.pr_facts
        sha = self.context.pr_head_sha or ""
        result = post_pull_request_review(self.context.pr, state, sha=sha)
        if result.skipped:
            console.print(f"[dim][GitHub] skip: {result.skip_reason}[/dim]")
            return True
        if result.ok:
            console.print(
                f"[green][GitHub] posted event={result.event} "
                f"inlines={result.inlines} skipped_inline={result.skipped_inline} "
                f"url={result.url or result.pr_url}[/green]"
            )
            return True
        console.print(f"[red][GitHub] post failed: {result.error}[/red]")
        if result.pr_url:
            console.print(f"[dim]PR: {result.pr_url}[/dim]")
        console.print("[dim]--- review body (not posted) ---[/dim]")
        console.print(result.body)
        return False

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
    dry_run: bool = typer.Option(
        True,
        "--dry-run/--no-dry-run",
        help="Default: do not post to GitHub. Use --no-dry-run or --comment to post.",
    ),
    comment: bool = typer.Option(
        False,
        "--comment",
        help="Post one GitHub PR review (summary only). Overrides default dry-run.",
    ),
    verbose: bool = typer.Option(
        False, "--verbose", "-v", help="Show detailed error information"
    ),
    execute_tests: bool = typer.Option(
        False,
        "--execute-tests",
        help="Opt-in: checkout PR HEAD and run pytest on related test files only",
    ),
    execute_install: bool = typer.Option(
        False,
        "--execute-install",
        help=(
            "Opt-in: uv sync / pip / npm ci --ignore-scripts in the worktree "
            "so tests can import. Implies network. No-op without --execute-tests."
        ),
    ),
    config_path: Optional[str] = typer.Option(
        None,
        "--config",
        help="Path to .codeturtle.yaml (else CODETURTLE_CONFIG or ./.codeturtle.yaml)",
    ),
):
    logger.info("Starting review", repo=repo, pr_number=number)
    ReviewPipeline().run(
        repo,
        number,
        dry_run,
        verbose,
        execute_tests=execute_tests,
        execute_install=execute_install,
        comment=comment,
        config_path=config_path or "",
    )
      