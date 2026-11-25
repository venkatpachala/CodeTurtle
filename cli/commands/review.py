import os
import time
from dataclasses import dataclass, field
from typing import Any, List, Optional

import typer
from github import Github
from rich.console import Console
from rich.panel import Panel

from config import settings
from core.memory.manager import LazyMemoryManager
from core.observability import get_langfuse_client, get_logger

logger = get_logger()
console = Console()
memory = LazyMemoryManager()


def _ollama_model_and_source() -> tuple[str, str]:
    """Process env beats .env. Leftover $env:OLLAMA_MODEL is a common trap."""
    env = str(os.environ.get("OLLAMA_MODEL") or "").strip()
    model = str(getattr(settings, "ollama_model", "") or "").strip()
    if env:
        return env, "env OLLAMA_MODEL"
    return model, ".env or default"


def _warn_if_ollama_model_missing(name: str) -> None:
    from cli.commands.wizard import list_ollama_models

    installed = list_ollama_models()
    if not installed or not name:
        return
    if name in installed or f"{name}:latest" in installed:
        return
    if any(m == name or m.startswith(name + ":") for m in installed):
        return
    shown = ", ".join(installed[:10])
    console.print(
        f"[red]Ollama has no model {name!r}. Installed: {shown}[/red]\n"
        "[dim]Process env OLLAMA_MODEL overrides .env. "
        "In PowerShell: Remove-Item Env:OLLAMA_MODEL[/dim]"
    )

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
    files_changed: List[str] = field(default_factory=list)
    full_diff: str = ""
    pr_facts: Optional[dict] = None
    final_state: Optional[dict] = None
    execute_tests: bool = False
    execute_install: bool = False
    pr_head_sha: str = ""
    pr_base_sha: str = ""
    intake_omissions: List[dict] = field(default_factory=list)
    publication: Optional[dict] = None
    publication_preview: Optional[dict] = None
    config_path: str = ""
    repo_cfg: Optional[object] = None
    change_units_payload: Optional[dict] = None
    repo_dir: str = ""
    review_intent: Optional[object] = None
    pr_input_provider: Optional[object] = None
    pr_review_snapshot: Optional[object] = None
    source_preparation: Optional[dict] = None


def get_current_session() -> str:
    from core.ci import ensure_session
    from core.user_config import session_file

    path = session_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    return ensure_session(str(path))


class ReviewPipeline:
    """Prepare a GitHub PR and deliver the canonical review result."""

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
        show_uncertain: bool = False,
        json_output: Optional[str] = None,
        approve: bool = False,
        expected_head_sha: str = "",
        expected_base_sha: str = "",
        github_auth: str = "configured",
        requirements_path: str = "",
    ):
        t0 = time.monotonic()
        from contextlib import ExitStack
        resources = ExitStack()
        try:
            from core.ci import github_authentication
            resources.enter_context(github_authentication(github_auth))
            from core.repo_config import (
                RepoConfigError,
                find_config_path,
                load_repo_config,
                merge_review_config,
            )

            self.context.repo = repo
            self.context.number = number
            self.context.config_path = config_path or ""
            self.context.review_intent = None
            if requirements_path:
                from pathlib import Path
                from core.intent.service import load_intent
                self.context.review_intent = load_intent(Path(requirements_path))

            try:
                cfg_path = find_config_path(config_path or None)
                repo_yaml = load_repo_config(cfg_path)
                cfg = merge_review_config(
                    repo=repo_yaml,
                    cli_execute_tests=bool(execute_tests),
                    cli_execute_install=bool(execute_install),
                    settings=settings,
                    config_path=cfg_path,
                )
            except RepoConfigError as exc:
                console.print(f"[red]{exc}[/red]")
                raise SystemExit(1) from exc

            self.context.repo_cfg = cfg
            self.context.execute_tests = bool(cfg.execute_tests)
            self.context.execute_install = bool(cfg.execute_install)
            if os.environ.get("GITHUB_ACTIONS") and (cfg.execute_tests or cfg.execute_install):
                raise ValueError("PR code execution is disabled in GitHub Actions; use a separate credential-free runner")
            if cfg.execute_tests or cfg.execute_install:
                raise ValueError("Host PR execution is disabled; use sandbox-check with a digest-pinned image")
            if cfg.model:
                settings.ollama_model = cfg.model
            if cfg.llm_backend:
                settings.llm_backend = cfg.llm_backend
            # Bundle and step limits stay on the per-review configuration.
            # Do not assign them onto Settings — extra="ignore" rejects unknown fields
            # and YAML defaults (bundle_max=4) would always trigger a write.
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

            model_name, model_source = _ollama_model_and_source()
            if settings.llm_backend == "openai":
                model_name = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
                model_source = "OPENAI_MODEL or default"
            if model_name:
                settings.ollama_model = model_name
            if settings.llm_backend == "ollama":
                _warn_if_ollama_model_missing(model_name)
            console.print(
                Panel.fit(
                    f"[bold cyan]CodeTurtle[/bold cyan]\n"
                    f"Session: {self.context.conversation_id}\n"
                    f"Repository: {repo}#{number}\n"
                    f"Model: {model_name} ({settings.llm_backend}, {model_source})"
                )
            )
            print(f"[Review] llm={model_name} source={model_source}")

            from core.ci import resolve_github_token
            from core.repository_knowledge.paths import resolve_repo_dir
            from core.workspace import WorkspaceError, ensure_checkout, ensure_index

            token = resolve_github_token(fallback=str(settings.github_token or ""))
            self._fetch_pr()
            if expected_head_sha and expected_head_sha != self.context.pr_head_sha:
                raise ValueError("PR HEAD differs from frozen input")
            if expected_base_sha and expected_base_sha != self.context.pr_base_sha:
                raise ValueError("PR BASE differs from frozen input")
            from core.review.lease import repository_lease
            from core.user_config import home_dir
            resources.enter_context(repository_lease(repo, home_dir()))
            try:
                checkout = ensure_checkout(
                    repo,
                    number,
                    token=token,
                    head_sha=self.context.pr_head_sha or "",
                )
                print(f"[Workspace] checkout={checkout}")
                if bool(getattr(settings, "graphify_enabled", False)):
                    try:
                        graph = ensure_index(repo)
                        print(f"[Workspace] graph={graph}")
                    except WorkspaceError as graph_exc:
                        console.print(
                            "[yellow][Workspace] Graphify unavailable; continuing "
                            f"with diff evidence: {graph_exc}[/yellow]"
                        )
                else:
                    print("[Workspace] graphify=disabled")
            except WorkspaceError as exc:
                console.print(f"[red]{exc}[/red]")
                raise SystemExit(1) from exc
            try:
                self.context.repo_dir = str(resolve_repo_dir(repo))
            except Exception:
                self.context.repo_dir = ""

            self._build_full_diff()
            self._prepare_source_snapshot()

            from core.output.terminal import render_result_terminal
            from core.runtime.review_runtime import ReviewRuntime, result_to_review_state

            console.print("[yellow]Running review runtime...[/yellow]")
            result = ReviewRuntime().run(self.context)
            self.context.final_state = result_to_review_state(result, self.context)
            self.context.final_state["_review_result"] = result
            self._add_langfuse_metadata()
            render_result_terminal(result, console=console, show_uncertain=show_uncertain)
            self._save_to_memory()

            if result.health.status == "failed":
                if json_output:
                    self._write_benchmark_json(json_output, elapsed=time.monotonic() - t0)
                raise SystemExit(1)
            posted = self._maybe_post(dry_run=dry_run, comment=comment, approve=approve)
            if json_output:
                self._write_benchmark_json(json_output, elapsed=time.monotonic() - t0)
            if posted is False:
                raise SystemExit(1)
            return self.context.final_state

        except _SkipReview as skip:
            console.print(f"[dim][Review] skip reason={skip.reason}[/dim]")
            if json_output:
                self._write_failure_json(json_output, skip.reason, skipped=True)
            return
        except SystemExit:
            raise
        except Exception as e:
            if json_output:
                self._write_failure_json(json_output, type(e).__name__)
            console.print(f"[red]Review failed: {type(e).__name__}[/red]")
            if verbose:
                console.print_exception(show_locals=False)
            raise SystemExit(1) from e
        finally:
            resources.close()

    def _write_failure_json(self, path: str, code: str, *, skipped: bool = False) -> None:
        from core.runtime.models import ReviewResult
        from core.review.contract import ReviewHealth, ReviewTarget, StageOutcome
        from core.review.artifacts import write_json_atomic
        result = ReviewResult(decision=None, policy_reason=code, policy_reasons=[code],
            health=ReviewHealth(status="skipped" if skipped else "failed",
                stages=[StageOutcome(stage="intake", status="skipped" if skipped else "failed", code=code)]),
            target=ReviewTarget(repo=self.context.repo, number=self.context.number,
                head_sha=self.context.pr_head_sha, base_sha=self.context.pr_base_sha))
        write_json_atomic(path, {**result.to_dict(), "review_comments": [], "decision": None})

    def _fetch_pr(self):
        from core.ci import resolve_github_token

        token = resolve_github_token(fallback=str(settings.github_token or ""))
        g = Github(token or None, timeout=30, retry=2)
        repo_obj = g.get_repo(self.context.repo)
        self.context.pr = repo_obj.get_pull(self.context.number)
        head = getattr(self.context.pr, "head", None)
        self.context.pr_head_sha = str(getattr(head, "sha", "") or "")
        self.context.pr_base_sha = str(getattr(self.context.pr.base, "sha", "") or "")
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
            else:
                self.context.intake_omissions.append({"file": name, "reason": "missing_patch"})
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

    def _prepare_source_snapshot(self):
        """Resolve comparison source before inference; retain missing history explicitly."""
        from core.input.preparation import prepare_pr_snapshot
        from core.input.snapshot import InputError
        self.context.pr_input_provider = None
        self.context.pr_review_snapshot = None
        try:
            provider, snapshot, report = prepare_pr_snapshot(
                self.context.repo_dir, self.context.pr_base_sha, self.context.pr_head_sha,
                self.context.full_diff)
            self.context.pr_input_provider = provider
            self.context.pr_review_snapshot = snapshot
            self.context.source_preparation = report
            print(f"[Source] pinned comparison ready base={snapshot.revision('base')[:12]} head={snapshot.head_sha[:12]}")
        except InputError as exc:
            self.context.source_preparation = {"status": "unavailable", "reason": str(exc)}
            print("[Source] pinned comparison unavailable; source-dependent conclusions remain unresolved")

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

    def _maybe_post(self, *, dry_run: bool, comment: bool, approve: bool = False) -> bool:
        from core.ci import resolve_github_token
        from core.output.publication import build_publication_plan, deliver_review, should_post

        result = self.context.final_state["_review_result"]
        plan = build_publication_plan(result, full_diff=self.context.full_diff, approve=approve,
            inline_max=int(getattr(self.context.repo_cfg, "inline_max", 8)))
        self.context.publication_preview = plan.to_dict()
        live = should_post(dry_run=dry_run, comment=comment)
        login = ""
        if live:
            token = resolve_github_token(fallback=str(settings.github_token or ""))
            login = "github-actions[bot]" if os.environ.get("GITHUB_ACTIONS") and not os.environ.get("CODETURTLE_GITHUB_TOKEN") else Github(token).get_user().login
        delivery = deliver_review(self.context.pr, plan, dry_run=not live, publisher_login=login)
        self.context.publication = delivery.to_dict()
        console.print(f"[GitHub] {delivery.status} event={plan.event} inlines={len(plan.comments)} {delivery.error_code}")
        return delivery.ok

    def _save_to_memory(self):
        final = self.context.final_state or {}
        memory.save_review(
            conversation_id=self.context.conversation_id,
            repo_name=self.context.repo,
            review_type="pr",
            number=self.context.number,
            title=str((self.context.pr_facts or {}).get("title") or ""),
            recommendation=final.get("recommendation", "N/A"),
            summary=str(final.get("final_comment", ""))[:600],
        )

    def _write_benchmark_json(self, json_path: str, elapsed: float = 0.0) -> None:
        from pathlib import Path
        from benchmark.adapter import review_result_to_benchmark_review

        review_result = self.context.final_state["_review_result"]
        model, _ = _ollama_model_and_source()
        payload = review_result_to_benchmark_review(
            review_result,
            repo=self.context.repo,
            number=self.context.number,
            elapsed=elapsed,
            model=review_result.provenance.get("model") or model or "qwen2.5:7b",
        ).to_dict()
        out_path = Path(json_path).resolve()
        # Retain the established top-level review_comments schema while also
        # exposing canonical v4 findings and diagnostics for benchmark runs.
        canonical = review_result.to_dict()
        payload["diagnostic_findings"] = canonical["findings"]
        payload["findings"] = canonical["product_findings"]
        payload["result"] = canonical
        for key in ("schema_version", "target", "health", "decision"):
            payload[key] = canonical[key]
        payload["publication_preview"] = self.context.publication_preview
        payload["publication"] = self.context.publication
        trace = getattr(review_result, "pipeline_trace", None)
        timing = getattr(review_result, "timing", None)
        payload["pipeline_trace"] = trace.to_list() if hasattr(trace, "to_list") else []
        payload["agent_runs"] = list(getattr(review_result, "agent_runs", []) or [])
        payload["pipeline_health"] = dict(getattr(review_result, "pipeline_health", {}) or {})
        trace_summary = trace.summary() if hasattr(trace, "summary") else {}
        payload["telemetry"] = {
            "timing": timing.to_dict() if hasattr(timing, "to_dict") else {},
            "agent_runs": list(getattr(review_result, "agent_runs", []) or []),
            "pipeline_health": dict(getattr(review_result, "pipeline_health", {}) or {}),
            "candidate_count": int(trace_summary.get("total_candidates") or 0),
            "verified_count": int(trace_summary.get("final_findings") or 0),
            "drop_reasons": dict(trace_summary.get("drop_reasons") or {}),
        }
        from core.review.artifacts import write_json_atomic
        write_json_atomic(out_path, payload)
        console.print(f"[dim][Benchmark] Wrote {out_path}[/dim]")


def review(
    target: str = typer.Argument(
        ...,
        help="owner/repo, owner/repo#N, or https://github.com/owner/repo/pull/N",
    ),
    number: Optional[int] = typer.Argument(
        None, help="PR number if not included in TARGET"
    ),
    dry_run: bool = typer.Option(
        True,
        "--dry-run/--no-dry-run",
        help="Default: do not post to GitHub. Use --no-dry-run or --comment to post.",
    ),
    comment: bool = typer.Option(
        False,
        "--comment",
        help="Post one GitHub PR review with summary and validated inlines. Overrides default dry-run.",
    ),
    approve: bool = typer.Option(False, "--approve", help="Explicitly approve an eligible complete MERGE recommendation when publishing"),
    expected_head_sha: str = typer.Option("", "--expected-head-sha", help="Reject a PR that differs from frozen HEAD"),
    expected_base_sha: str = typer.Option("", "--expected-base-sha", help="Reject a PR that differs from frozen BASE"),
    github_auth: str = typer.Option("configured", "--github-auth", help="Credential source: configured, gh, or anonymous"),
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
    show_uncertain: bool = typer.Option(
        False,
        "--show-uncertain",
        help="Print PLAUSIBLE_BUT_UNPROVEN drops. They never set Decision.",
    ),
    json_output: Optional[str] = typer.Option(
        None,
        "--json-output",
        help="Write structured review output to a JSON file.",
    ),
    requirements: Optional[str] = typer.Option(
        None, "--requirements", help="Explicit user-supplied scoped requirements JSON; never auto-loaded from the PR",
    ),
):
    from core.cli_parse import parse_review_target

    raw = (target or "").strip()
    if number is not None and not (
        "#" in raw.split("/")[-1] or "/pull/" in raw.lower()
    ):
        raw = f"{raw} {int(number)}"
    try:
        repo, number = parse_review_target(raw)
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        raise SystemExit(2) from exc
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
        show_uncertain=show_uncertain,
        json_output=json_output,
        approve=approve,
        expected_head_sha=expected_head_sha,
        expected_base_sha=expected_base_sha,
        github_auth=github_auth,
        requirements_path=requirements or "",
    )
