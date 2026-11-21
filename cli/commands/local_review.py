"""Review sealed committed trees without checkout, publication, or execution."""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import os
from enum import Enum

import typer

from core.input.snapshot import GitSnapshotProvider, InputError
from core.intent.service import load_intent
from core.review.artifacts import write_json_atomic
from core.runtime.review_runtime import ReviewRuntime
from core.verification.diff_index import build_diff_index


class RequirementStrategy(str, Enum):
    INVESTIGATE = "investigate"
    LINK = "link"
    OFF = "off"


def review_local(
    base: str = typer.Option(..., "--base", help="Exact base tree/ref; compares BASE directly with HEAD"),
    head: str = typer.Option("HEAD", "--head"),
    repo: Path = typer.Option(Path("."), "--repo", exists=True, file_okay=False),
    requirements: Path | None = typer.Option(None, "--requirements", exists=True, dir_okay=False),
    json_output: Path = typer.Option(Path("review-local.json"), "--json-output"),
    static_only: bool = typer.Option(False, "--static-only", help="Run deterministic rules; no model calls; inspection remains incomplete"),
    requirement_strategy: RequirementStrategy = typer.Option(RequirementStrategy.INVESTIGATE, "--requirement-strategy",
        help="Investigate each requirement, link existing findings only, or disable intent for ablation"),
    max_requirements: int = typer.Option(8, "--max-requirements", min=0, max=32, help="Requirement task admission cap"),
):
    """Review committed code. Dirty and untracked changes are deliberately excluded."""
    try:
        intent = load_intent(requirements) if requirements else None
        provider = GitSnapshotProvider(repo)
        from config import settings
        from core.agent.bundle_agent import PROMPT_VERSION
        config = {"analysis_mode": "static_only" if static_only else "model",
                  "intent_hash": intent.source.content_hash if intent else None,
                  "provider": settings.llm_backend,
                  "model": os.environ.get("OPENAI_MODEL", "gpt-4o-mini") if settings.llm_backend == "openai"
                           else settings.ollama_model,
                  "prompt_version": PROMPT_VERSION, "rules_enabled": settings.rules_enabled,
                  "ollama_context_tokens": settings.ollama_context_tokens if settings.llm_backend == "ollama" else None,
                  "verification_enabled": settings.verification_enabled}
        config.update(requirement_strategy=requirement_strategy.value, max_requirements=max_requirements)
        snapshot = provider.resolve(base, head, config=config)
        diff = provider.diff(snapshot)
        index = build_diff_index(diff)
        files = sorted(index.files)
        context = SimpleNamespace(
            repo="", number=0, repo_dir="", files_changed=files, full_diff=diff,
            pr_head_sha=snapshot.head_sha, pr_base_sha=snapshot.base_sha,
            review_snapshot=snapshot, input_provider=provider, review_intent=intent,
            requirement_strategy=requirement_strategy.value, max_requirements=max_requirements,
            analysis_mode=config["analysis_mode"],
        )
        runtime = ReviewRuntime()
        result = runtime.run(context)
        result.provenance["analysis_mode"] = config["analysis_mode"]
        write_json_atomic(json_output, result.to_dict())
        typer.echo(f"Sealed committed review: {snapshot.id[:12]}")
        typer.echo(f"{len(result.product_findings)} verified finding(s); recommendation: {result.decision}")
        typer.echo(f"Inspected {result.inspection.inspected}/{result.inspection.eligible} eligible units")
        typer.echo(f"Report: {json_output.resolve()}")
        if static_only:
            typer.echo("Static-only run: no model quality or complete-inspection claim.")
    except (InputError, ValueError, OSError) as exc:
        typer.echo(f"Local review failed: {exc}", err=True)
        raise typer.Exit(1) from exc
