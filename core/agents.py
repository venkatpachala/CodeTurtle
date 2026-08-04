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

def _diff_for_review(state: dict, max_chars: int = 14000) -> str:
    diff = (state.get("full_diff") or "").strip()
    return diff[:max_chars] if diff else "(no diff)"


def _files_block(state: dict) -> str:
    files = state.get("files_changed") or []
    return "\n".join(files) if files else "(none)"


def _expand_evidence(
    refs,
    files_changed: list | None,
    allowed: set[str],
) -> list[str]:
    """
    Keep strict path evidence when possible; if the model only cited a basename
    or a partial path, map it onto files_changed / allowed paths.
    """
    files_changed = list(files_changed or [])
    primary = _normalize_evidence(refs, allowed)
    if primary:
        return primary

    out: list[str] = []
    blob = " ".join(str(r) for r in (refs or []))
    lowered = blob.lower()

    for f in files_changed:
        base = f.split("/")[-1]
        if f in blob or base in blob or f.lower() in lowered or base.lower() in lowered:
            out.append(f)

    for a in allowed:
        base = a.split("/")[-1]
        if a in blob or base in blob:
            out.append(a)

    # Last resort: if model returned any non-empty evidence strings and we have
    # exactly one changed file, attribute to that file (better than dropping).
    if not out and refs and len(files_changed) == 1:
        out = [files_changed[0]]

    return list(dict.fromkeys(out))


def _ground_findings(
    raw_list,
    *,
    files_changed: list,
    context_from_kb: str,
    category: str,
    id_prefix: str,
) -> list[dict]:
    allowed = _paths_from_context(context_from_kb) | set(files_changed or [])
    grounded = []
    for i, f in enumerate(raw_list or []):
        d = _finding_to_dict(f)
        refs = d.get("evidence") or d.get("evidence_refs") or d.get("evidence_ids") or []
        ev = _expand_evidence(refs, files_changed, allowed)
        if not ev:
            continue
        d["evidence"] = ev
        d["category"] = category
        d.setdefault("id", f"{id_prefix}-{i}")
        grounded.append(d)
    return grounded

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
            "correctness_meta": {"skipped": True, "raw": 0, "grounded": 0},
            "traces": [{"agent": "CorrectnessAgent", "output": "skipped (not in review_plan)"}],
        }

    pr_understanding = state.get("pr_understanding") or {}
    pr_analysis = state.get("pr_analysis") or {}
    plan = state.get("review_plan") or {}
    focus = plan.get("focus_notes") if isinstance(plan, dict) else []
    rich_context = (state.get("context_from_kb") or "")[:8000]
    diff = _diff_for_review(state)
    files = _files_block(state)
    files_changed = list(state.get("files_changed") or [])

    prompt = ChatPromptTemplate.from_messages([
        ("system", """You are a Correctness Reviewer for a GitHub Pull Request.

PRIMARY SOURCE OF TRUTH: the unified DIFF of changed files.
SECONDARY: retrieved repository evidence (for definitions/callers only).

HARD RULES:
1. Review the DIFF first. Every finding must point to a concrete change in the diff
   (file path and, if possible, changed behavior).
2. evidence MUST be a non-empty list of repo-relative paths from the changed-file list
   when possible (e.g. graphify/build.py) or path:line from the diff.
3. Do NOT invent files, APIs, or behaviors absent from the diff or evidence.
4. Do NOT treat truncated evidence snippets as "incomplete code in the repo".
5. Prefer real defects: logic errors, regressions, broken invariants, missing
   edge cases in the changed code. Skip pure style.
6. Prefer 0 findings over generic advice ("ensure tests", "review carefully").
7. If the diff looks correct for the stated bugfix, return an EMPTY findings list."""),
        ("human", """PR Understanding:
{pr_understanding}

PR Analysis:
{pr_analysis}

Review focus:
{focus}

Changed files:
{files}

=== UNIFIED DIFF (PRIMARY) ===
{diff}

=== RETRIEVED REPO EVIDENCE (SECONDARY) ===
{rich_context}

Return Findings for correctness issues grounded in the DIFF.
If none, return findings=[]."""),
    ]).format(
        pr_understanding=pr_understanding,
        pr_analysis=pr_analysis,
        focus=focus,
        files=files,
        diff=diff,
        rich_context=rich_context or "(none)",
    )

    result = gateway.generate_structured(
        prompt=prompt,
        schema=Findings,
        capability="correctness_review",
        agent_name="CorrectnessAgent",
        temperature=0.1,
        max_tokens=2000,
    )

    raw_list = list(result.findings if hasattr(result, "findings") else [])
    grounded = _ground_findings(
        raw_list,
        files_changed=files_changed,
        context_from_kb=rich_context + "\n" + diff,
        category="correctness",
        id_prefix="corr",
    )

    # Temporary: uncomment if raw>0 grounded==0
    # if raw_list and not grounded:
    #     print("CORRECTNESS DROP", [_finding_to_dict(x) for x in raw_list])

    meta = {
        "skipped": False,
        "raw": len(raw_list),
        "grounded": len(grounded),
        "no_issues_in_diff": len(grounded) == 0,
    }

    return {
        "correctness_findings": grounded,
        "correctness_meta": meta,
        "traces": [{
            "agent": "CorrectnessAgent",
            "output": (
                f"raw={meta['raw']} grounded={meta['grounded']} "
                f"no_issues={meta['no_issues_in_diff']}"
            ),
        }],
    }


def code_quality_agent(state: ReviewState) -> dict:
    if not _should_run(state, "code_quality"):
        return {
            "quality_findings": [],
            "quality_meta": {"skipped": True, "raw": 0, "grounded": 0},
            "traces": [{"agent": "CodeQualityAgent", "output": "skipped (not in review_plan)"}],
        }

    evidence_package = state.get("evidence_package")
    pr_understanding = state.get("pr_understanding") or {}
    pr_analysis = state.get("pr_analysis") or {}
    rich_context = (state.get("context_from_kb") or "")[:12000]
    diff = _diff_for_review(state, max_chars=10000)
    files_changed = list(state.get("files_changed") or [])
    files = _files_block(state)

    evidence_summary = ""
    if evidence_package is not None and hasattr(evidence_package, "summary"):
        evidence_summary = evidence_package.summary or ""

    prompt = ChatPromptTemplate.from_messages([
        ("system", """You are a Code Quality Reviewer for a GitHub Pull Request.

PRIMARY: unified DIFF of changed files.
SECONDARY: retrieved evidence/context.

HARD RULES:
1. Only use the diff, evidence/context, and PR metadata provided.
2. evidence MUST be a non-empty list; prefer repo-relative paths from the
   changed-file list (e.g. graphify/build.py).
3. If evidence is insufficient, return zero findings.
4. Focus on maintainability, API clarity, duplication, error-handling structure,
   testability — not pure nitpicks or style-only comments.
5. Never invent code that was not retrieved or shown in the diff.
6. Do NOT report "incomplete functions" solely because a retrieved snippet is truncated.
7. Prefer 0 findings over generic advice."""),
        ("human", """PR Understanding:
{pr_understanding}

PR Analysis:
{pr_analysis}

Changed files:
{files}

Evidence summary:
{evidence_summary}

=== UNIFIED DIFF (PRIMARY) ===
{diff}

=== RETRIEVED EVIDENCE (SECONDARY) ===
{rich_context}

Return Findings: only grounded code quality issues.
If none, return findings=[]."""),
    ]).format(
        pr_understanding=pr_understanding,
        pr_analysis=pr_analysis,
        files=files,
        evidence_summary=evidence_summary or "(see context)",
        diff=diff,
        rich_context=rich_context or "(no evidence)",
    )

    result = gateway.generate_structured(
        prompt=prompt,
        schema=Findings,
        capability="code_quality_review",
        agent_name="CodeQualityAgent",
        temperature=0.15,
        max_tokens=2000,
    )

    raw_list = list(result.findings if hasattr(result, "findings") else [])
    grounded = _ground_findings(
        raw_list,
        files_changed=files_changed,
        context_from_kb=rich_context + "\n" + diff,
        category="code_quality",
        id_prefix="qual",
    )

    meta = {
        "skipped": False,
        "raw": len(raw_list),
        "grounded": len(grounded),
    }

    return {
        "quality_findings": grounded,
        "quality_meta": meta,
        "traces": [{
            "agent": "CodeQualityAgent",
            "output": f"raw={meta['raw']} grounded={meta['grounded']}",
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

    context = state.get("context_from_kb") or ""

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
    understanding = state.get("pr_understanding") or {}
    risk = understanding.get("risk_level", "medium") if isinstance(understanding, dict) else "medium"
    summary_u = understanding.get("summary", "") if isinstance(understanding, dict) else ""

    sev = [str(f.get("severity", "low")).lower() for f in finding_dicts]
    if any(s in ("critical", "high") for s in sev):
        baseline = "REQUEST_CHANGES"
    elif any(s == "medium" for s in sev):
        baseline = "COMMENT"
    else:
        baseline = "MERGE"

    corr_meta = state.get("correctness_meta") or {}
    test_meta = state.get("testing_meta") or {}

    prompt = ChatPromptTemplate.from_messages([
        ("system", """You are the final maintainer decision.

Rules:
- recommendation MUST be MERGE | REQUEST_CHANGES | COMMENT
- summary MUST only use: PR understanding summary + kept findings
- Do NOT invent features, bugs, or subsystems not present there
- If kept findings is empty → MERGE (mention residual risk only if understanding risk is high/critical)
- High/critical findings → REQUEST_CHANGES"""),
        ("human", """Understanding summary: {summary_u}
Risk: {risk}
Baseline: {baseline}
Correctness meta: {corr_meta}
Testing meta: {test_meta}

Kept findings JSON:
{findings}

Return ReviewOutput."""),
    ]).format(
        summary_u=summary_u,
        risk=risk,
        baseline=baseline,
        corr_meta=corr_meta,
        test_meta=test_meta,
        findings=json.dumps(finding_dicts, indent=2)[:6000],
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
            "testing_meta": {
                "skipped": True,
                "raw": 0,
                "grounded": 0,
                "tests_touched": False,
            },
            "traces": [{"agent": "TestingAgent", "output": "skipped (not in review_plan)"}],
        }

    pr_understanding = state.get("pr_understanding") or {}
    pr_analysis = state.get("pr_analysis") or {}
    rich_context = (state.get("context_from_kb") or "")[:12000]
    diff = _diff_for_review(state, max_chars=10000)
    files_changed = list(state.get("files_changed") or [])
    files = _files_block(state)

    tests_touched = any(
        "test" in str(f).lower() or str(f).endswith("_test.py")
        for f in files_changed
    )
    analysis_tests = False
    if isinstance(pr_analysis, dict):
        analysis_tests = bool(pr_analysis.get("tests_added_or_modified"))

    prompt = ChatPromptTemplate.from_messages([
        ("system", """You are a Testing Reviewer for a GitHub PR.

PRIMARY: unified DIFF and changed-file list.
SECONDARY: retrieved evidence/context.

HARD RULES:
1. Only use the PR diff, file list, and retrieved evidence/context.
2. evidence MUST be a non-empty list; prefer repo-relative paths from the
   changed-file list (e.g. tests/test_build.py, graphify/build.py).
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

=== UNIFIED DIFF (PRIMARY) ===
{diff}

=== RETRIEVED EVIDENCE (SECONDARY) ===
{rich_context}

Return Findings: only concrete testing gaps grounded in evidence/diff.
If none, return findings=[]."""),
    ]).format(
        pr_understanding=pr_understanding,
        pr_analysis=pr_analysis,
        files=files,
        tests_touched=tests_touched,
        analysis_tests=analysis_tests,
        diff=diff or "(no diff)",
        rich_context=rich_context or "(no evidence)",
    )

    result = gateway.generate_structured(
        prompt=prompt,
        schema=Findings,
        capability="reasoning",  # or "testing_review" if registered
        agent_name="TestingAgent",
        temperature=0.15,
        max_tokens=1500,
    )

    raw_list = list(result.findings if hasattr(result, "findings") else [])
    grounded = _ground_findings(
        raw_list,
        files_changed=files_changed,
        context_from_kb=rich_context + "\n" + diff,
        category="testing",
        id_prefix="test",
    )

    meta = {
        "skipped": False,
        "raw": len(raw_list),
        "grounded": len(grounded),
        "tests_touched": tests_touched,
    }

    return {
        "testing_findings": grounded,
        "testing_meta": meta,
        "traces": [{
            "agent": "TestingAgent",
            "output": (
                f"raw={meta['raw']} grounded={meta['grounded']} "
                f"tests_touched={tests_touched}"
            ),
        }],
    }