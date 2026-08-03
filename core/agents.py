from __future__ import annotations

import json
import re
from typing import Any, Dict, Iterable, List, Set

from langchain_core.prompts import ChatPromptTemplate

from core.state import ReviewState
from core.models import Finding, ReviewOutput, Findings
from core.gateway import gateway
from core.review_intelligence.models import ReviewPlan, RetrievalQuestion, MergeDecision


# ── Evidence helpers ─────────────────────────────────────────────────────────

def _reviewers_from_state(state: dict) -> set[str]:
    plan = state.get("review_plan") or {}
    raw = plan.get("reviewers") if isinstance(plan, dict) else []
    out = set()
    for r in raw or []:
        if hasattr(r, "value"):
            out.add(str(r.value).lower())
        else:
            out.add(str(r).lower())
    # If planner produced nothing, keep legacy defaults
    if not out:
        out = {"correctness", "code_quality"}
    return out


def _should_run(state: dict, kind: str) -> bool:
    return kind in _reviewers_from_state(state)


def _paths_from_context(context_from_kb: str) -> Set[str]:
    if not context_from_kb:
        return set()
    found = set(re.findall(r"path=([^\s\n]+)", context_from_kb))
    found |= set(
        re.findall(
            r"`([a-zA-Z0-9_./\\-]+\.(?:py|ts|js|go|rs|md|toml|yml|yaml))`",
            context_from_kb,
        )
    )
    found |= set(
        re.findall(
            r"(?:^|\s)([a-zA-Z0-9_./\\-]+/(?:[a-zA-Z0-9_./\\-]+)\.(?:py|ts|js|go|rs|md))",
            context_from_kb,
        )
    )
    return {p.strip().strip("`") for p in found if p}


def _finding_to_dict(f: Any) -> dict:
    if hasattr(f, "model_dump"):
        return f.model_dump()
    if isinstance(f, dict):
        return dict(f)
    return {
        "id": "unknown",
        "title": str(f),
        "description": str(f),
        "severity": "low",
        "confidence": 0.0,
        "evidence": [],
        "reasoning": "",
        "recommendation": "",
        "category": "unknown",
    }


def _normalize_evidence(refs, allowed):
    out = []
    for r in refs or []:
        s = str(r).strip()
        if not s:
            continue
        if not allowed:
            if "/" in s or s.startswith("["):
                out.append(s)
            continue
        if any(a in s for a in allowed) or any(s in a or a in s for a in allowed):
            out.append(s)
            continue
        base = s.split(":")[0].strip()
        if base in allowed or "/" in s:
            out.append(s)
    return list(dict.fromkeys(out))


def _filter_grounded_findings(findings: List[Any], context_from_kb: str) -> List[dict]:
    allowed = _paths_from_context(context_from_kb)
    kept: List[dict] = []
    for i, f in enumerate(findings or []):
        d = _finding_to_dict(f)
        ev = _normalize_evidence(
            d.get("evidence") or d.get("evidence_refs") or d.get("evidence_ids") or [],
            allowed,
        )
        if not ev:
            continue
        d["evidence"] = ev
        d.setdefault("id", f"f-{i}")
        d.setdefault("category", d.get("category") or "review")
        d.setdefault("description", d.get("description") or d.get("reasoning") or "")
        d.setdefault("reasoning", d.get("reasoning") or "")
        d.setdefault("recommendation", d.get("recommendation") or "")
        kept.append(d)
    return kept


# ── Context agents ───────────────────────────────────────────────────────────

def context_summarizer(state: ReviewState) -> dict:
    prompt = ChatPromptTemplate.from_messages([
        ("system", """You are an expert repository analyst.

Create a concise, high-signal summary of the repository context relevant to this PR.

Focus on:
- Key files and modules touched
- Relevant symbols, classes, functions
- Architecture patterns
- Dependencies

Be technical and precise. Do not speculate."""),
        ("human", """PR Title: {title}

Retrieved Repository Context:
{raw_context}

Summarize only the most relevant parts for code review."""),
    ]).format(
        title=state.get("title", ""),
        raw_context=state.get("context_from_kb") or "",
    )

    response = gateway.generate(
        prompt=prompt,
        capability="summarization",
        temperature=0.2,
        max_tokens=600,
        agent_name="ContextSummarizer",
    )
    content = getattr(response, "content", None) or str(response)

    return {
        "summarized_context": content,
        "traces": [{"agent": "ContextSummarizer", "output": content}],
    }


def context_gatherer(state: ReviewState) -> dict:
    prompt = ChatPromptTemplate.from_messages([
        ("system", """You are an expert PR context gatherer.

Create a focused summary for downstream reviewers:
- Main intent of the PR
- Key changes
- Potential impact areas
- What reviewers should focus on

Do not invent files or APIs."""),
        ("human", """PR Title: {title}

PR Body: {body}

Summarized Repository Context:
{context_to_use}

Provide a concise, actionable summary for code reviewers."""),
    ]).format(
        title=state.get("title", ""),
        body=state.get("body", "") or "",
        context_to_use=state.get("summarized_context") or "",
    )

    response = gateway.generate(
        prompt=prompt,
        capability="context_gathering",
        temperature=0.3,
        max_tokens=800,
        agent_name="ContextGatherer",
    )
    content = getattr(response, "content", None) or str(response)

    return {
        "context_summary": content,
        "traces": [{"agent": "ContextGatherer", "output": content}],
    }


# ── Specialist reviewers ─────────────────────────────────────────────────────

def correctness_agent(state: ReviewState) -> dict:
    if not _should_run(state, "correctness"):
        return {
            "correctness_findings": [],
            "traces": [{"agent": "CorrectnessAgent", "output": "skipped (not in review_plan)"}],
        }
    evidence_package = state.get("evidence_package")
    pr_understanding = state.get("pr_understanding", {})
    pr_analysis = state.get("pr_analysis", {})
    rich_context = (state.get("context_from_kb") or "")[:12000]

    evidence_summary = ""
    if evidence_package is not None and hasattr(evidence_package, "summary"):
        evidence_summary = evidence_package.summary or ""

    plan = state.get("review_plan") or {}
    focus = plan.get("focus_notes") if isinstance(plan, dict) else []

    prompt = ChatPromptTemplate.from_messages([
        ("system", """You are a Correctness Reviewer for a GitHub PR.

HARD RULES:
1. You may ONLY use the PR metadata and the Evidence / context blocks provided.
2. Every finding MUST include a non-empty "evidence" list of paths or path:line refs
   that appear in the evidence (e.g. graphify/build.py or graphify/build.py:120-140).
3. If you cannot ground a claim in evidence, DO NOT emit that finding.
4. Prefer 0 findings over ungrounded or generic advice.
5. Focus on real defects: logic errors, edge cases, broken invariants, regressions,
   missing error handling — not style.
6. Do not invent APIs, files, or behaviors absent from evidence/diff."""),
        ("human", """PR Understanding:
{pr_understanding}

PR Analysis:
{pr_analysis}

Review focus notes:
{focus}

Evidence summary:
{evidence_summary}

Retrieved evidence / context:
{rich_context}

Diff (truncated):
{diff}

Return Findings: only grounded correctness issues."""),
    ]).format(
        pr_understanding=pr_understanding,
        pr_analysis=pr_analysis,
        focus=focus,
        evidence_summary=evidence_summary or "(see context)",
        rich_context=rich_context or "(no evidence)",
        diff=(state.get("full_diff") or "")[:8000],
    )

    result = gateway.generate_structured(
        prompt=prompt,
        schema=Findings,
        capability="correctness_review",
        agent_name="CorrectnessAgent",
        temperature=0.15,
        max_tokens=2000,
    )

    raw = result.findings if hasattr(result, "findings") else []
    grounded = _filter_grounded_findings(raw, rich_context)
    for d in grounded:
        d["category"] = "correctness"

    return {
        "correctness_findings": grounded,
        "traces": [{
            "agent": "CorrectnessAgent",
            "output": f"raw={len(raw)} grounded={len(grounded)}",
        }],
    }


def code_quality_agent(state: ReviewState) -> dict:
    if not _should_run(state, "code_quality"):
        return {
            "quality_findings": [],
            "traces": [{"agent": "CodeQualityAgent", "output": "skipped (not in review_plan)"}],
        }
    evidence_package = state.get("evidence_package")
    pr_understanding = state.get("pr_understanding", {})
    pr_analysis = state.get("pr_analysis", {})
    rich_context = (state.get("context_from_kb") or "")[:12000]

    evidence_summary = ""
    if evidence_package is not None and hasattr(evidence_package, "summary"):
        evidence_summary = evidence_package.summary or ""

    prompt = ChatPromptTemplate.from_messages([
        ("system", """You are a Code Quality Reviewer.

HARD RULES:
1. Only use provided evidence/context and PR metadata.
2. Every finding MUST include non-empty evidence paths from the context.
3. If evidence is insufficient, return zero findings.
4. Focus on maintainability, API clarity, duplication, error-handling structure,
   testability — not pure nitpicks.
5. Never invent code that was not retrieved."""),
        ("human", """PR Understanding:
{pr_understanding}

PR Analysis:
{pr_analysis}

Evidence summary:
{evidence_summary}

Retrieved evidence / context:
{rich_context}

Diff (truncated):
{diff}

Return Findings: only grounded code quality issues."""),
    ]).format(
        pr_understanding=pr_understanding,
        pr_analysis=pr_analysis,
        evidence_summary=evidence_summary or "(see context)",
        rich_context=rich_context or "(no evidence)",
        diff=(state.get("full_diff") or "")[:8000],
    )

    result = gateway.generate_structured(
        prompt=prompt,
        schema=Findings,
        capability="code_quality_review",
        agent_name="CodeQualityAgent",
        temperature=0.15,
        max_tokens=2000,
    )

    raw = result.findings if hasattr(result, "findings") else []
    grounded = _filter_grounded_findings(raw, rich_context)
    for d in grounded:
        d["category"] = "code_quality"

    return {
        "quality_findings": grounded,
        "traces": [{
            "agent": "CodeQualityAgent",
            "output": f"raw={len(raw)} grounded={len(grounded)}",
        }],
    }


# ── Evidence package (plan-driven) ───────────────────────────────────────────

def build_evidence_package(state: dict) -> dict:
    from core.query_engine import RepositoryQueryEngine

    repo = state["repo"]
    engine = state.get("engine")
    if engine is None:
        engine = RepositoryQueryEngine(repo, kb=state.get("kb"))

    plan_raw = state.get("review_plan") or {}
    try:
        plan = ReviewPlan.model_validate(plan_raw) if plan_raw else None
    except Exception:
        plan = None

    files_changed = list(state.get("files_changed") or [])
    understanding = state.get("pr_understanding") or {}

    packages = []
    if plan and plan.retrieval_questions:
        for q in plan.retrieval_questions[:10]:
            if isinstance(q, dict):
                q = RetrievalQuestion.model_validate(q)
            pkg = engine.retrieve_context(
                query=q.question,
                files_changed=q.prefer_paths or files_changed,
                symbols=q.prefer_symbols or [],
                k=6,
                pr_understanding=understanding if isinstance(understanding, dict) else {},
            )
            packages.append(pkg)
    else:
        query = f"{state.get('title', '')}\n{state.get('body', '')}"
        packages.append(
            engine.retrieve_context(
                query=query,
                files_changed=files_changed,
                k=8,
                pr_understanding=understanding if isinstance(understanding, dict) else {},
            )
        )

    evidence_package = _merge_packages(packages, max_items=16)
    rich_context = _format_evidence(evidence_package)

    n_q = len(plan.retrieval_questions) if plan else 0
    n_ev = len(getattr(evidence_package, "evidences", None) or [])

    return {
        "evidence_package": evidence_package,
        "context_from_kb": rich_context,
        "traces": [{
            "agent": "BuildEvidencePackage",
            "output": f"plan_questions={n_q} merged={n_ev}",
        }],
    }


def _merge_packages(packages, max_items: int = 16):
    if not packages:
        return None
    seen = set()
    merged = []
    for pkg in packages:
        for ev in getattr(pkg, "evidences", None) or []:
            path = getattr(ev, "path", "") or ""
            content = (getattr(ev, "content", None) or getattr(ev, "page_content", "") or "")[:80]
            key = (path, content)
            if key in seen:
                continue
            seen.add(key)
            merged.append(ev)
            if len(merged) >= max_items:
                break
        if len(merged) >= max_items:
            break

    head = packages[0]
    try:
        from dataclasses import replace, is_dataclass
        if is_dataclass(head) and hasattr(head, "evidences"):
            return replace(head, evidences=merged)
    except Exception:
        pass
    try:
        head.evidences = merged
        if hasattr(head, "count"):
            head.count = len(merged)
    except Exception:
        pass
    return head


def _format_evidence(evidence_package) -> str:
    if evidence_package is None:
        return "(no evidence)"
    try:
        from core.context_builder import ContextBuilder
        return ContextBuilder.to_agent_context(evidence_package)
    except Exception:
        lines = []
        for i, ev in enumerate(getattr(evidence_package, "evidences", None) or [], 1):
            path = getattr(ev, "path", "") or ""
            content = (
                getattr(ev, "content", None) or getattr(ev, "page_content", "") or ""
            )[:1500]
            lines.append(f"[{i}] path={path}\n{content}\n")
        return "\n".join(lines) if lines else "(no evidence)"


# ── Critic ───────────────────────────────────────────────────────────────────

def critic_agent(state: ReviewState) -> dict:
    """
    Reasoning gate: drop empty evidence / duplicates / generic advice.
    Outputs state['findings'] = kept only (for final_recommender).
    """
    correctness = list(state.get("correctness_findings") or [])
    quality = list(state.get("quality_findings") or [])
    testing = list(state.get("testing_findings") or [])

    combined: List[dict] = []
    for src, cat in (
        (correctness, "correctness"),
        (quality, "code_quality"),
        (testing, "testing"),
    ):
        for f in src:
            d = _finding_to_dict(f)
            d["category"] = d.get("category") or cat
            combined.append(d)

    # Deterministic: empty evidence already filtered upstream, but re-check
    pre_kept, pre_dropped = [], []
    for d in combined:
        ev = d.get("evidence") or []
        if not ev:
            pre_dropped.append({"title": d.get("title", "?"), "reason": "no_evidence"})
            continue
        title = (d.get("title") or "").lower()
        desc = (d.get("description") or d.get("reasoning") or "").lower()
        generic = (
            "ensure that" in desc
            and "test" in desc
            and not ev
        ) or title in ("looks good", "no issues")
        if generic:
            pre_dropped.append({"title": d.get("title", "?"), "reason": "generic"})
            continue
        pre_kept.append(d)

    # De-dupe by normalized title
    seen_titles = set()
    deduped = []
    for d in pre_kept:
        key = re.sub(r"\s+", " ", (d.get("title") or "").lower().strip())
        if key in seen_titles:
            pre_dropped.append({"title": d.get("title", "?"), "reason": "duplicate"})
            continue
        seen_titles.add(key)
        deduped.append(d)

    prompt = ChatPromptTemplate.from_messages([
        ("system", """You are a strict PR review critic (reasoning gate), NOT a second code reviewer.

Rules:
- KEEP only if evidence paths support the claim.
- DROP duplicates, generic advice, or inflated severity without substance.
- MERGE near-duplicates into one tighter finding (put result in findings list).
- Do NOT invent new findings.
- Prefer fewer, sharper findings.

Return Findings: the final kept list only."""),
        ("human", """PR title: {title}

Context (truncated):
{context}

Candidate findings (JSON):
{candidates}

Already dropped (informational):
{dropped}

Return only the findings to KEEP."""),
    ]).format(
        title=state.get("title", ""),
        context=context[:6000],
        candidates=json.dumps(deduped, indent=2)[:8000],
        dropped=json.dumps(pre_dropped, indent=2)[:2000],
    )

    try:
        result = gateway.generate_structured(
            prompt=prompt,
            schema=Findings,
            capability="reasoning",
            agent_name="CriticAgent",
            temperature=0.1,
            max_tokens=2000,
        )
        llm_findings = result.findings if hasattr(result, "findings") else []
        kept = _filter_grounded_findings(llm_findings, context)
        if not deduped:
            return {
                "findings": [],
                "critique": {
                    "kept": [],
                    "dropped": pre_dropped,
                    "notes": "in=0 after_det=0 kept=0 (no candidates; skip LLM invent)",
                },
                "traces": [{"agent": "CriticAgent", "output": "empty_input_no_llm"}],
            }
    except Exception:
        kept = deduped

    critique = {
        "kept": kept,
        "dropped": pre_dropped,
        "notes": f"in={len(combined)} after_det={len(deduped)} kept={len(kept)}",
    }

    return {
        "findings": kept,
        "critique": critique,
        "traces": [{
            "agent": "CriticAgent",
            "output": critique["notes"] + " dropped=" + str(pre_dropped)[:500],
        }],
    }


# ── Final decision ───────────────────────────────────────────────────────────

def final_recommender(state: ReviewState) -> dict:
    findings = list(state.get("findings") or [])
    finding_dicts = [_finding_to_dict(f) for f in findings]

    sev = [str(f.get("severity", "low")).lower() for f in finding_dicts]
    if any(s in ("critical", "high") for s in sev):
        baseline = "REQUEST_CHANGES"
    elif any(s == "medium" for s in sev):
        baseline = "COMMENT"
    else:
        baseline = "MERGE"

    understanding = state.get("pr_understanding") or {}
    risk = understanding.get("risk_level", "medium") if isinstance(understanding, dict) else "medium"

    prompt = ChatPromptTemplate.from_messages([
        ("system", """You are the final maintainer decision for a GitHub PR.

Rules:
- recommendation MUST be exactly one of: MERGE, REQUEST_CHANGES, COMMENT
- Do not invent issues not present in the findings list
- If findings is empty and risk is low → MERGE
- High/critical findings → REQUEST_CHANGES
- Medium-only → COMMENT or REQUEST_CHANGES
- summary: max 5 sentences, decision-focused, professional"""),
        ("human", """PR risk (understanding): {risk}
Severity baseline: {baseline}

Kept findings (JSON):
{findings}

Context summary:
{context_summary}

Return ReviewOutput with recommendation, summary, confidence."""),
    ]).format(
        risk=risk,
        baseline=baseline,
        findings=json.dumps(finding_dicts, indent=2)[:6000],
        context_summary=(state.get("context_summary") or "")[:2000],
    )

    try:
        response = gateway.generate_structured(
            prompt=prompt,
            schema=ReviewOutput,
            capability="final_recommendation",
            agent_name="FinalRecommender",
            temperature=0.1,
            max_tokens=800,
        )
        rec = str(getattr(response, "recommendation", None) or baseline).upper()
        if rec not in ("MERGE", "REQUEST_CHANGES", "COMMENT"):
            rec = baseline
        summary = getattr(response, "summary", None) or ""
        confidence = float(getattr(response, "confidence", None) or 0.6)
    except Exception:
        rec = baseline
        summary = f"Automated decision based on {len(finding_dicts)} kept findings."
        confidence = 0.55

    blocking = [
        f.get("title")
        for f in finding_dicts
        if str(f.get("severity", "")).lower() in ("high", "critical")
    ]

    final_comment = (
        f"**{rec}** (confidence={confidence:.2f})\n\n"
        f"{summary}\n\n"
        f"Findings kept: {len(finding_dicts)}\n"
        f"Blocking: {blocking or 'none'}"
    )

    return {
        "final_comment": final_comment,
        "recommendation": rec,
        "merge_decision": {
            "recommendation": rec,
            "confidence": confidence,
            "summary": summary,
            "blocking_issues": blocking,
        },
        "traces": [{"agent": "FinalRecommender", "output": final_comment[:2000]}],
    }

def testing_agent(state: ReviewState) -> dict:
    """Check whether tests adequately cover the PR change."""
    if not _should_run(state, "testing"):
        return {
            "testing_findings": [],
            "traces": [{"agent": "TestingAgent", "output": "skipped (not in review_plan)"}],
        }

    pr_understanding = state.get("pr_understanding") or {}
    pr_analysis = state.get("pr_analysis") or {}
    rich_context = (state.get("context_from_kb") or "")[:12000]
    diff = (state.get("full_diff") or "")[:10000]
    files = state.get("files_changed") or []

    tests_touched = any(
        "test" in str(f).lower() or str(f).endswith("_test.py")
        for f in files
    )
    analysis_tests = False
    if isinstance(pr_analysis, dict):
        analysis_tests = bool(pr_analysis.get("tests_added_or_modified"))

    prompt = ChatPromptTemplate.from_messages([
        ("system", """You are a Testing Reviewer for a GitHub PR.

HARD RULES:
1. Only use the PR diff, file list, and retrieved evidence/context.
2. Every finding MUST include non-empty evidence paths from the context or changed test files.
3. Prefer 0 findings over generic "add more tests" with no specifics.
4. Focus on:
   - Bug/fix behavior claimed in the PR but not asserted in tests
   - Missing edge cases clearly implied by the diff
   - Tests that don't actually exercise the changed code
5. If tests look adequate for the stated bugfix, return zero findings.
6. Do not invent files or test names not present in evidence/diff."""),
        ("human", """PR Understanding:
{pr_understanding}

PR Analysis:
{pr_analysis}

Files changed:
{files}

Deterministic signals:
- tests_in_changed_files: {tests_touched}
- analysis.tests_added_or_modified: {analysis_tests}

Diff (truncated):
{diff}

Retrieved evidence / context:
{rich_context}

Return Findings: only concrete testing gaps grounded in evidence/diff."""),
    ]).format(
        pr_understanding=pr_understanding,
        pr_analysis=pr_analysis,
        files="\n".join(files) if files else "(none)",
        tests_touched=tests_touched,
        analysis_tests=analysis_tests,
        diff=diff or "(no diff)",
        rich_context=rich_context or "(no evidence)",
    )

    result = gateway.generate_structured(
        prompt=prompt,
        schema=Findings,
        capability="reasoning",  # or add "testing_review" to registry
        agent_name="TestingAgent",
        temperature=0.15,
        max_tokens=1500,
    )

    raw = result.findings if hasattr(result, "findings") else []
    grounded = _filter_grounded_findings(raw, rich_context + "\n" + diff)
    # For tests, also accept evidence paths that appear in files_changed
    if not grounded and raw:
        allowed = set(files) | _paths_from_context(rich_context)
        grounded = []
        for i, f in enumerate(raw):
            d = _finding_to_dict(f)
            ev = _normalize_evidence(d.get("evidence") or [], allowed)
            if not ev:
                continue
            d["evidence"] = ev
            d["category"] = "testing"
            d.setdefault("id", f"test-{i}")
            grounded.append(d)
    else:
        for d in grounded:
            d["category"] = "testing"

    return {
        "testing_findings": grounded,
        "traces": [{
            "agent": "TestingAgent",
            "output": f"raw={len(raw)} grounded={len(grounded)} tests_touched={tests_touched}",
        }],
    }