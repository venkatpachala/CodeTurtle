"""Review Planner — dynamic review plan from PR understanding + analysis."""

from __future__ import annotations

import json
from typing import Any

from core.review_intelligence.models import (
    ReviewPlan,
    ReviewerKind,
    RetrievalQuestion,
)
from core.gateway import gateway


def _as_dict(x: Any) -> dict:
    if x is None:
        return {}
    if isinstance(x, dict):
        return x
    if hasattr(x, "model_dump"):
        return x.model_dump()
    return {}


def _deterministic_reviewers(understanding: dict, analysis: dict) -> list[ReviewerKind]:
    reviewers: set[ReviewerKind] = set()

    files = [str(f).lower() for f in (analysis.get("changed_files") or [])]
    body = " ".join(
        [
            str(understanding.get("summary") or ""),
            str(understanding.get("intent") or ""),
            " ".join(str(x) for x in (understanding.get("change_types") or [])),
            " ".join(files),
        ]
    ).lower()

    only_docs = bool(files) and all(
        f.endswith((".md", ".rst", ".txt")) or "docs/" in f or f.startswith("docs")
        for f in files
    )

    if only_docs:
        return [ReviewerKind.DOCUMENTATION]

    reviewers.add(ReviewerKind.CORRECTNESS)
    reviewers.add(ReviewerKind.CODE_QUALITY)

    if analysis.get("tests_added_or_modified") or any(
        "test" in f for f in files
    ):
        reviewers.add(ReviewerKind.TESTING)
    else:
        # Code change without tests → still want testing reviewer to flag gaps
        if any(f.endswith((".py", ".ts", ".js", ".go", ".rs")) for f in files):
            reviewers.add(ReviewerKind.TESTING)

    risk = str(understanding.get("risk_level") or analysis.get("risk_level") or "low").lower()
    if risk in ("high", "critical"):
        reviewers.add(ReviewerKind.ARCHITECTURE)

    security_hints = ("auth", "crypto", "password", "token", "sql", "exec", "inject", "permission")
    if any(h in body for h in security_hints):
        reviewers.add(ReviewerKind.SECURITY)

    concurrency_hints = ("async", "lock", "thread", "concurrent", "race", "mutex", "asyncio")
    if any(h in body for h in concurrency_hints):
        reviewers.add(ReviewerKind.CONCURRENCY)

    perf_hints = ("perf", "latency", "cache", "memory", "cpu", "optim")
    if any(h in body for h in perf_hints):
        reviewers.add(ReviewerKind.PERFORMANCE)

    if analysis.get("documentation_changed") and ReviewerKind.DOCUMENTATION not in reviewers:
        # optional docs pass alongside code
        pass

    api_hints = ("api", "breaking", "public", "endpoint", "compat")
    if any(h in body for h in api_hints):
        reviewers.add(ReviewerKind.API_COMPAT)

    return sorted(reviewers, key=lambda r: r.value)


def _deterministic_questions(understanding: dict, analysis: dict) -> list[RetrievalQuestion]:
    questions: list[RetrievalQuestion] = []
    files = list(analysis.get("changed_files") or [])[:12]
    added = list(analysis.get("added_functions") or [])[:10]
    modified = list(analysis.get("modified_functions") or [])[:10]

    title = str(understanding.get("summary") or understanding.get("intent") or "")[:200]

    if title:
        questions.append(
            RetrievalQuestion(
                question=title,
                purpose="intent_semantic",
                prefer_paths=files[:5],
            )
        )

    for path in files[:8]:
        questions.append(
            RetrievalQuestion(
                question=f"implementation and usage of {path}",
                purpose="changed_file",
                prefer_paths=[path],
            )
        )

    for name in (added + modified)[:8]:
        questions.append(
            RetrievalQuestion(
                question=f"function {name} definition and callers",
                purpose="changed_symbol",
                prefer_symbols=[name],
                prefer_paths=files[:3],
            )
        )

    if not analysis.get("tests_added_or_modified"):
        questions.append(
            RetrievalQuestion(
                question="tests related to " + (", ".join(files[:3]) or "this change"),
                purpose="missing_tests",
                prefer_paths=[f for f in files if "test" in f.lower()][:3],
            )
        )

    # de-dupe by question text
    seen = set()
    unique: list[RetrievalQuestion] = []
    for q in questions:
        key = q.question.strip().lower()
        if key in seen:
            continue
        seen.add(key)
        unique.append(q)
    return unique[:15]


def _llm_enrich_plan(
    understanding: dict,
    analysis: dict,
    base: ReviewPlan,
) -> ReviewPlan:
    """Optional LLM pass: extra questions + focus notes. Falls back to base on failure."""
    prompt = f"""You are a senior maintainer planning a PR review.

PR understanding (JSON):
{json.dumps(understanding, indent=2)[:3000]}

PR analysis (JSON):
{json.dumps(analysis, indent=2)[:3000]}

Already selected reviewers: {[r.value for r in base.reviewers]}

Return JSON with:
- intent_summary: one sentence
- risk_level: low|medium|high|critical
- focus_notes: 3-6 short bullets of what to verify
- extra_questions: list of {{"question": str, "purpose": str}} (max 5) for code search

Do not invent files. Prefer questions about behavior, callers, edge cases, regressions.
"""

    try:
        # Plain text then light parse, or structured if you add a schema
        resp = gateway.generate(
            prompt=prompt,
            capability="reasoning",
            temperature=0.2,
            max_tokens=800,
            agent_name="ReviewPlanner",
        )
        text = getattr(resp, "content", None) or str(resp)
        # Keep deterministic reviewers; only merge notes/questions if JSON-like
        focus = list(base.focus_notes)
        extras: list[RetrievalQuestion] = []
        # Best-effort: if model returns markdown, still keep base questions
        if "focus" in text.lower():
            focus.append(text[:500])
        return base.model_copy(
            update={
                "intent_summary": base.intent_summary or text[:240],
                "focus_notes": focus[:8],
                "retrieval_questions": list(base.retrieval_questions) + extras,
            }
        )
    except Exception:
        return base


def review_planner_agent(state: dict) -> dict:
    """
    LangGraph node: build ReviewPlan after pr_understanding + pr_analysis.
    """
    understanding = _as_dict(state.get("pr_understanding"))
    analysis = _as_dict(state.get("pr_analysis"))

    reviewers = _deterministic_reviewers(understanding, analysis)
    questions = _deterministic_questions(understanding, analysis)

    risk = str(
        understanding.get("risk_level")
        or understanding.get("risk")
        or "medium"
    ).lower()

    intent = str(
        understanding.get("summary")
        or understanding.get("intent")
        or state.get("title")
        or ""
    )[:400]

    plan = ReviewPlan(
        intent_summary=intent,
        risk_level=risk if risk in ("low", "medium", "high", "critical") else "medium",
        reviewers=reviewers,
        retrieval_questions=questions,
        focus_notes=[
            f"Changed files: {len(analysis.get('changed_files') or [])}",
            f"Added functions: {analysis.get('added_functions') or []}",
            f"Modified functions: {analysis.get('modified_functions') or []}",
        ],
        skip_reasons={},
    )

    # Optional LLM enrich (comment out if you want pure deterministic first)
    plan = _llm_enrich_plan(understanding, analysis, plan)

    return {
        "review_plan": plan.model_dump(mode="json"),
        "traces": [
            {
                "agent": "ReviewPlanner",
                "output": plan.model_dump_json(indent=2)[:4000],
            }
        ],
    }