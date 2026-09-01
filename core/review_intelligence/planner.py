"""Review Planner — hypothesis-driven review plan from PR understanding + analysis."""

from __future__ import annotations

import json
from typing import Any

from core.review_intelligence.models import (
    ReviewPlan,
    ReviewerKind,
    RetrievalQuestion,
)
from core.investigation.planner import deterministic_investigate_asks
from core.gateway import gateway


def _as_dict(x: Any) -> dict:
    if x is None:
        return {}
    if isinstance(x, dict):
        return x
    if hasattr(x, "model_dump"):
        return x.model_dump()
    return {}


def _clean_notes(notes: list[Any]) -> list[str]:
    """Drop metadata dumps, JSON blobs, and markdown fences."""
    out: list[str] = []
    skip_prefixes = (
        "changed files:",
        "added functions:",
        "modified functions:",
        "```",
        "{",
    )
    for n in notes or []:
        s = str(n).strip()
        if not s:
            continue
        low = s.lower()
        if any(low.startswith(p) for p in skip_prefixes):
            continue
        if s.startswith("```") or (s.startswith("{") and "intent_summary" in s):
            continue
        out.append(s)
    return out


def _resolve_modified_symbols(analysis: dict) -> list[str]:
    modified = [str(x) for x in (analysis.get("modified_functions") or [])]
    constants = [str(x) for x in (analysis.get("constants_added") or [])]
    added = [str(x) for x in (analysis.get("added_functions") or [])]
    return (modified + constants + added)[:10]


def _deterministic_reviewers(understanding: dict, analysis: dict) -> list[ReviewerKind]:
    reviewers: set[ReviewerKind] = set()

    files = [str(f).lower() for f in (analysis.get("changed_files") or [])]
    body = " ".join(
        [
            str(understanding.get("summary") or ""),
            " ".join(str(x) for x in (understanding.get("change_type") or [])),
            " ".join(str(x) for x in (understanding.get("change_types") or [])),
            " ".join(files),
            " ".join(str(x) for x in (analysis.get("logic_changes") or [])),
        ]
    ).lower()

    only_docs = bool(files) and all(
        f.endswith((".md", ".rst", ".txt")) or "docs/" in f or f.startswith("docs")
        for f in files
    )
    if only_docs:
        return [ReviewerKind.DOCUMENTATION]

    risk = str(
        understanding.get("risk_level") or analysis.get("risk_level") or "low"
    ).lower()

    # Core path bug/policy → bump risk for reviewer allocation
    core_hints = ("core", "engine", "main", "runtime", "auth", "db", "api", "server", "client", "model", "service", "security")
    if risk == "low" and any(any(h in f for h in core_hints) for f in files):
        if "bug" in body or "fix" in body or "invariant" in body:
            risk = "medium"

    # Always correctness for code
    reviewers.add(ReviewerKind.CORRECTNESS)

    # Testing: present tests or missing-tests gap
    if analysis.get("tests_added_or_modified") or any("test" in f for f in files):
        reviewers.add(ReviewerKind.TESTING)
    elif any(f.endswith((".py", ".ts", ".js", ".go", ".rs", ".java", ".cpp", ".c")) for f in files):
        reviewers.add(ReviewerKind.TESTING)

    # Code quality only when risk medium+ or large surface — not default for tiny policy fixes
    if risk in ("medium", "high", "critical") or len(files) > 3:
        reviewers.add(ReviewerKind.CODE_QUALITY)

    if risk in ("high", "critical") or "invariant" in body or "architecture" in body:
        if hasattr(ReviewerKind, "ARCHITECTURE"):
            reviewers.add(ReviewerKind.ARCHITECTURE)

    security_hints = (
        "auth", "crypto", "password", "token", "sql", "exec", "inject", "permission",
    )
    if any(h in body for h in security_hints) and hasattr(ReviewerKind, "SECURITY"):
        reviewers.add(ReviewerKind.SECURITY)

    concurrency_hints = (
        "async", "lock", "thread", "concurrent", "race", "mutex", "asyncio",
    )
    if any(h in body for h in concurrency_hints) and hasattr(ReviewerKind, "CONCURRENCY"):
        reviewers.add(ReviewerKind.CONCURRENCY)

    perf_hints = ("perf", "latency", "cache", "memory", "cpu", "optim")
    if any(h in body for h in perf_hints) and hasattr(ReviewerKind, "PERFORMANCE"):
        reviewers.add(ReviewerKind.PERFORMANCE)

    api_hints = ("api", "breaking", "public", "endpoint", "compat")
    if any(h in body for h in api_hints) and hasattr(ReviewerKind, "API_COMPAT"):
        reviewers.add(ReviewerKind.API_COMPAT)

    return sorted(reviewers, key=lambda r: r.value)


def _deterministic_questions(
    understanding: dict, analysis: dict
) -> list[RetrievalQuestion]:
    """Hypothesis / invariant-driven questions — not 'implementation of file'."""
    from core.pr_facts import question_grounded_in_pr

    questions: list[RetrievalQuestion] = []
    files = list(analysis.get("changed_files") or [])[:12]
    diff = analysis.get("full_diff") or ""
    code_files = [p for p in files if "test" not in p.lower()]
    test_files = [p for p in files if "test" in p.lower()]

    def _real(names: list) -> list[str]:
        out: list[str] = []
        for n in names or []:
            s = str(n).strip()
            if s and question_grounded_in_pr(s, files, diff):
                out.append(s)
        return out

    added = _real(list(analysis.get("added_functions") or [])[:10])
    modified = _real(_resolve_modified_symbols(analysis))
    constants = _real(list(analysis.get("constants_added") or [])[:10])
    tests = _real(list(analysis.get("added_test_functions") or [])[:8])

    summary = str(understanding.get("summary") or "")[:180]
    if summary:
        questions.append(
            RetrievalQuestion(
                question=f"Code related to: {summary}",
                purpose="intent_semantic",
                prefer_paths=files[:5],
                prefer_symbols=(modified + constants)[:5],
            )
        )

    for sym in modified[:5]:
        questions.append(
            RetrievalQuestion(
                question=(
                    f"Definition of {sym} and how it handles parameters, "
                    f"return values, or error conditions"
                ),
                purpose="changed_symbol",
                prefer_symbols=[sym],
                prefer_paths=code_files[:3] or files[:3],
            )
        )
        questions.append(
            RetrievalQuestion(
                question=f"Callers and downstream usages of {sym}",
                purpose="downstream_callers",
                prefer_symbols=[sym],
                prefer_paths=[],
            )
        )

    for name in added[:5]:
        questions.append(
            RetrievalQuestion(
                question=f"Definition and purpose of helper {name}",
                purpose="changed_symbol",
                prefer_symbols=[name],
                prefer_paths=files[:3],
            )
        )

    for c in constants[:5]:
        questions.append(
            RetrievalQuestion(
                question=f"Definition and uses of constant {c}",
                purpose="priority_or_config",
                prefer_symbols=[c],
                prefer_paths=code_files[:2] or files[:2],
            )
        )

    # Dynamic question based on review_hotspots and logic_changes
    hotspots = list(analysis.get("review_hotspots") or [])[:3]
    logic = list(analysis.get("logic_changes") or [])[:2]
    if hotspots or logic:
        focus_str = ", ".join(str(x) for x in (hotspots + logic))[:120]
        questions.append(
            RetrievalQuestion(
                question=f"Implementation & invariants for: {focus_str}",
                purpose="collapse_policy",
                prefer_paths=code_files[:3] or files[:3],
                prefer_symbols=(modified + constants)[:5],
            )
        )

    # Blast radius / caller question
    if modified or constants or added:
        sym_str = ", ".join((modified + constants + added)[:3])
        questions.append(
            RetrievalQuestion(
                question=f"Downstream callers, consumers, or affected callers of {sym_str}",
                purpose="blast_radius",
                prefer_paths=[],
                prefer_symbols=(modified + constants + added)[:5],
            )
        )

    if analysis.get("tests_added_or_modified") or test_files:
        tested_target = ", ".join(modified[:3]) or "changed logic"
        questions.append(
            RetrievalQuestion(
                question=f"Tests covering {tested_target}",
                purpose="regression_tests",
                prefer_paths=test_files[:3] or [p for p in files if "test" in p.lower()],
                prefer_symbols=tests[:5],
            )
        )
    else:
        questions.append(
            RetrievalQuestion(
                question="Existing tests related to "
                + (", ".join(code_files[:2]) or "this change"),
                purpose="missing_tests",
                prefer_paths=test_files[:3],
            )
        )

    seen: set[str] = set()
    unique: list[RetrievalQuestion] = []
    for q in questions:
        q_text = q.question.strip()
        for bad_prefix in ("implementation and usage of ", "implementation of ", "usage of "):
            if q_text.lower().startswith(bad_prefix):
                q_text = q_text[len(bad_prefix):].strip()
        q.question = q_text
        key = q.question.strip().lower()
        if key in seen or not key:
            continue
        seen.add(key)
        unique.append(q)
    return unique[:8]


def _deterministic_focus_notes(understanding: dict, analysis: dict) -> list[str]:
    notes: list[str] = []
    for key in (
        "logic_changes",
        "behavior_changes",
        "behavioral_invariants",
        "architectural_changes",
        "design_assumptions",
    ):
        for item in (analysis.get(key) or [])[:3]:
            notes.append(str(item))
    for t in (understanding.get("verification_targets") or [])[:4]:
        notes.append(f"Verify: {t}")
    for t in (understanding.get("focus_areas") or [])[:3]:
        notes.append(str(t))
    if analysis.get("tests_added_or_modified"):
        notes.append("Confirm regression tests cover changed execution paths where relevant")
    return _clean_notes(notes)[:10]


def _resolve_risk(understanding: dict, analysis: dict) -> str:
    risk = str(
        understanding.get("risk_level")
        or analysis.get("risk_level")
        or "medium"
    ).lower()
    files = [str(f).lower() for f in (analysis.get("changed_files") or [])]
    core_hints = ("core", "engine", "main", "runtime", "auth", "db", "api", "server", "client", "model", "service", "security")
    if risk == "low" and any(any(h in f for h in core_hints) for f in files):
        risk = "medium"
    if risk not in ("low", "medium", "high", "critical"):
        risk = "medium"
    return risk


def _filter_grounded_questions(
    questions: list[RetrievalQuestion],
    files_changed: list,
    full_diff: str,
) -> list[RetrievalQuestion]:
    from core.pr_facts import question_grounded_in_pr

    out: list[RetrievalQuestion] = []
    for q in questions or []:
        if question_grounded_in_pr(q.question, files_changed, full_diff):
            out.append(q)
    return out


def _llm_enrich_plan(
    understanding: dict,
    analysis: dict,
    base: ReviewPlan,
) -> ReviewPlan:
    """Optional: refine intent_summary + extra focus notes only. Never replace questions wholesale."""
    files_changed = analysis.get("changed_files") or []
    full_diff = (analysis.get("full_diff") or "").strip()

    prompt = f"""You are a senior maintainer refining a PR review plan.

Changed files (authoritative):
{files_changed}

Diff excerpt:
{full_diff[:8000]}

Retrieval questions may only name paths in files_changed
or identifiers that appear in the diff excerpt.
Do not invent FakeConnection / FakeCursor unless those strings are in the diff.
Focus notes must follow the same rule.

Understanding:
{json.dumps(understanding, indent=2)[:2500]}

Analysis:
{json.dumps(analysis, indent=2)[:2500]}

Current intent_summary: {base.intent_summary}
Current risk_level: {base.risk_level}
Reviewers: {[r.value for r in base.reviewers]}

Reply with plain text ONLY in this format (no JSON, no markdown fences):
INTENT: <one sentence causal summary>
NOTES:
- <verification bullet>
- <verification bullet>
- <verification bullet>
"""

    try:
        resp = gateway.generate(
            prompt=prompt,
            capability="reasoning",
            temperature=0.2,
            max_tokens=500,
            agent_name="ReviewPlanner",
        )
        text = (getattr(resp, "content", None) or str(resp)).strip()

        intent = base.intent_summary
        extra_notes: list[str] = []
        if text.startswith("INTENT:"):
            line0 = text.split("\n", 1)[0]
            intent = line0.replace("INTENT:", "", 1).strip() or intent
        for line in text.splitlines():
            s = line.strip()
            if s.startswith("- "):
                extra_notes.append(s[2:].strip())

        notes = _clean_notes(list(base.focus_notes) + extra_notes)[:10]
        return base.model_copy(
            update={
                "intent_summary": intent[:400],
                "focus_notes": notes,
                # keep deterministic retrieval_questions
                "retrieval_questions": list(base.retrieval_questions),
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
    files = list(state.get("files_changed") or analysis.get("changed_files") or [])
    diff = state.get("full_diff") or ""
    analysis = {
        **analysis,
        "changed_files": files or list(analysis.get("changed_files") or []),
        "full_diff": diff,
    }

    reviewers = _deterministic_reviewers(understanding, analysis)
    questions = _filter_grounded_questions(
        _deterministic_questions(understanding, analysis),
        files,
        diff,
    )
    risk = _resolve_risk(understanding, analysis)
    intent = str(
        understanding.get("summary")
        or state.get("title")
        or ""
    )[:400]
    focus_notes = _deterministic_focus_notes(understanding, analysis)

    investigate_asks = deterministic_investigate_asks(files, diff)

    plan = ReviewPlan(
        intent_summary=intent,
        risk_level=risk,
        reviewers=reviewers,
        retrieval_questions=questions,
        investigate=investigate_asks,
        focus_notes=focus_notes,
        skip_reasons={},
    )

    plan = _llm_enrich_plan(understanding, analysis, plan)
    # Final sanitize after LLM — drop invented Fake* questions even if enrich kept them
    investigate_asks = [
        a
        for a in list(plan.investigate or [])
        if a.file
        and any(
            a.file.replace("\\", "/") == f.replace("\\", "/")
            or a.file.replace("\\", "/").endswith("/" + f.replace("\\", "/").split("/")[-1])
            or f.replace("\\", "/").endswith("/" + a.file.replace("\\", "/").split("/")[-1])
            for f in files
        )
    ]
    from core.investigation.planner import strip_ungrounded_symbol, is_investigable_path

    cleaned_asks = []
    for a in investigate_asks:
        path = is_investigable_path(a.file, files)
        if not path:
            continue
        a.file = path
        a.symbol = strip_ungrounded_symbol(a.symbol, files, diff)
        cleaned_asks.append(a)

    plan = plan.model_copy(
        update={
            "focus_notes": _clean_notes(plan.focus_notes)[:10],
            "retrieval_questions": _filter_grounded_questions(
                list(plan.retrieval_questions), files, diff
            ),
            "investigate": cleaned_asks[:3],
        }
    )

    return {
        "review_plan": plan.model_dump(mode="json"),
        "traces": [
            {
                "agent": "ReviewPlanner",
                "output": plan.model_dump_json(indent=2)[:4000],
            }
        ],
    }