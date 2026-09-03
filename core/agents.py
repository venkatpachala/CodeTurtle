from __future__ import annotations

import json
import re
from typing import Any, Dict, Iterable, List, Set

from langchain_core.prompts import ChatPromptTemplate

from core.state import ReviewState
from core.models import (
    Finding,
    ReviewOutput,
    Findings,
    FindingSeverity,
    SpecialistFinding,
    SpecialistReview,
)
from core.gateway import gateway
from core.review_intelligence.models import ReviewPlan, RetrievalQuestion, MergeDecision


# ── Review substance guard ───────────────────────────────────────────────────

def ensure_review_substance(review: SpecialistReview, agent: str) -> SpecialistReview:
    """
    Guard against total abstention only — never inject fabricated findings.
    """
    has_signal = bool(review.findings) or bool((review.summary or "").strip())
    if not has_signal:
        review.summary = f"{agent}: no structured review produced — treat as abstention."
        review.residual_risks = list(review.residual_risks or []) + [
            "Specialist abstained — manual review recommended"
        ]
        review.no_blocking_issues = False
    return review


def _ground_specialist_review(
    review: SpecialistReview,
    *,
    files_changed: list[str],
    context_from_kb: str,
    category: str,
    id_prefix: str,
) -> SpecialistReview:
    """Map cited paths onto files_changed. Do not invent a file the model omitted."""
    allowed = set(files_changed or [])
    grounded_findings: list[SpecialistFinding] = []

    for f in review.findings or []:
        if f.file:
            f.file = str(f.file).replace("\\", "/")
        raw_paths = list(f.evidence_paths or [])
        if f.file and f.file not in raw_paths:
            raw_paths = [f.file] + raw_paths
        ev = _expand_evidence(raw_paths, files_changed, allowed)
        if ev:
            f.evidence_paths = ev
            if not f.file:
                f.file = ev[0]
        else:
            f.evidence_paths = [str(p).replace("\\", "/") for p in raw_paths if p]
        sev_str = (f.severity.value if hasattr(f.severity, "value") else str(f.severity)).lower()
        if sev_str == "blocking" and not ev:
            f.severity = FindingSeverity.concern
            f.detail = f"[Ungrounded blocker converted to concern] {f.detail}"
        grounded_findings.append(f)

    review.findings = grounded_findings
    return review


# ── Evidence / path helpers ──────────────────────────────────────────────────

def _reviewers_from_state(state: dict) -> set[str]:
    plan = state.get("review_plan") or {}
    raw = plan.get("reviewers") if isinstance(plan, dict) else []
    out = set()
    for r in raw or []:
        if hasattr(r, "value"):
            out.add(str(r.value).lower())
        else:
            out.add(str(r).lower())
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

    return list(dict.fromkeys(out))


def _ground_findings(
    raw_list,
    *,
    files_changed: list,
    context_from_kb: str,
    category: str,
    id_prefix: str,
) -> list[dict]:
    allowed = set(files_changed or [])
    grounded = []
    for i, f in enumerate(raw_list or []):
        d = _finding_to_dict(f)
        refs = d.get("evidence") or d.get("evidence_refs") or d.get("evidence_paths") or []
        ev = _expand_evidence(refs, files_changed, allowed)
        d["evidence"] = ev
        if not d.get("file") and ev:
            d["file"] = ev[0]
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
        d = f.model_dump()
    elif isinstance(f, dict):
        d = dict(f)
    else:
        return {
            "id": "unknown",
            "title": str(f),
            "description": str(f),
            "claim": "",
            "severity": "low",
            "confidence": 0.0,
            "evidence": [],
            "file": None,
            "symbol": None,
            "start_line": None,
            "end_line": None,
            "reasoning": "",
            "recommendation": "",
            "category": "unknown",
        }
    if "detail" in d and not d.get("description"):
        d["description"] = d["detail"]
    if "detail" in d and not d.get("reasoning"):
        d["reasoning"] = d["detail"]
    if not d.get("claim"):
        d["claim"] = d.get("title") or ""
    if not d.get("evidence"):
        d["evidence"] = d.get("evidence_paths") or d.get("evidence_refs") or []
    if hasattr(d.get("severity"), "value"):
        d["severity"] = d["severity"].value
    if d.get("file"):
        d["file"] = str(d["file"]).replace("\\", "/")
    if not d.get("file") and d.get("evidence"):
        first = d["evidence"][0] if isinstance(d["evidence"], list) and d["evidence"] else None
        if first:
            d["file"] = str(first).replace("\\", "/")
    d.setdefault("symbol", d.get("symbol"))
    d.setdefault("start_line", d.get("start_line"))
    d.setdefault("end_line", d.get("end_line"))
    d.setdefault("needs_investigation", bool(d.get("needs_investigation")))
    d.setdefault("question", d.get("question") or "")
    d.setdefault("evidence_ids", d.get("evidence_ids") or [])
    return d


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
        if not ev and not allowed:
            # no path metadata available — keep if title non-empty
            if (d.get("title") or "").strip():
                d.setdefault("id", f"f-{i}")
                kept.append(d)
            continue
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


# ── Specialist context helpers ───────────────────────────────────────────────

# High-signal PR behavior keywords (domain-agnostic + common review axes)
_PR_BEHAVIOR_KEYWORDS = {
    "priority", "collapse", "overwrite", "invariant", "relation",
    "undirected", "edge", "duplicate", "conflict", "race", "lock",
    "auth", "token", "header", "ssrf", "inject", "sanitize",
    "retry", "timeout", "cache", "session", "compat", "breaking",
    "regression", "order", "deterministic", "null", "empty",
}


def filter_evidence_for_pr(
    raw_context: str,
    pr_symbols: set[str],
    diff: str,
    changed_files: list[str] | None = None,
    max_chunks: int = 8,
) -> str:
    """
    Keep only evidence chunks that clearly relate to the PR.

    Anchors (strict):
    - PR symbols from Phase-2 analysis
    - changed file path / basename
    - NOT every token from the full diff (that re-admits noise)
    """
    if not raw_context or not raw_context.strip():
        return "(no evidence)"

    changed_files = list(changed_files or [])
    anchor_terms: set[str] = set()

    for sym in pr_symbols:
        s = str(sym).strip()
        if len(s) >= 3:
            anchor_terms.add(s.lower())

    for path in changed_files:
        p = str(path).replace("\\", "/")
        anchor_terms.add(p.lower())
        base = p.split("/")[-1]
        if base:
            anchor_terms.add(base.lower())
            stem = base.rsplit(".", 1)[0]
            if len(stem) >= 3:
                anchor_terms.add(stem.lower())

    # Only high-value identifiers from the diff (def/class/const names), not all words
    for m in re.finditer(
        r"(?:def|class|async def|const|let|var|function)\s+([A-Za-z_][A-Za-z0-9_]{2,})",
        diff or "",
    ):
        anchor_terms.add(m.group(1).lower())
    for m in re.finditer(r"^[\+\-]\s*([A-Z_][A-Z0-9_]{2,})\s*=", diff or "", re.M):
        anchor_terms.add(m.group(1).lower())

    separators = re.split(r"(?=\[\d+\]|path=|--- |\+\+\+ |\n{2,})", raw_context)
    paragraphs = [p.strip() for p in separators if p.strip()]

    scored: list[tuple[int, str]] = []
    for para in paragraphs:
        para_lower = para.lower()
        score = 0
        for term in anchor_terms:
            if term and term in para_lower:
                # Prefer longer symbol matches
                score += max(1, min(len(term) // 4, 5))
        if score > 0:
            scored.append((score, para))

    scored.sort(key=lambda x: -x[0])
    kept = [p for _, p in scored[:max_chunks]]

    # No weak fallback to arbitrary paragraphs — better empty than noise
    if not kept:
        # Last resort: paragraphs that mention a changed file path only
        for para in paragraphs:
            pl = para.lower()
            if any(str(f).replace("\\", "/").lower() in pl for f in changed_files):
                kept.append(para)
            if len(kept) >= max_chunks:
                break

    if not kept:
        return (
            "(no PR-relevant evidence chunks after filter — "
            "rely on the UNIFIED DIFF and Phase-2 analysis only)"
        )

    return "\n\n".join(kept)


def _extract_pr_symbols(pr_analysis: dict) -> set[str]:
    """Extract PR-relevant symbols from Phase-2 analysis."""
    syms: set[str] = set()
    for key in (
        "modified_functions",
        "added_functions",
        "removed_functions",
        "constants_added",
        "added_test_functions",
        "modified_test_functions",
        "review_hotspots",
        "modified_classes",
        "added_classes",
    ):
        for item in pr_analysis.get(key) or []:
            if item:
                syms.add(str(item).strip())
    return syms


def _pr_keyword_set(pr_analysis: dict, understanding: dict, diff: str) -> set[str]:
    """Compact keyword set for relevance checks — not full diff bag-of-words."""
    keys = set(_PR_BEHAVIOR_KEYWORDS)
    for sym in _extract_pr_symbols(pr_analysis):
        if len(sym) >= 3:
            keys.add(sym.lower())
    for key in ("logic_changes", "behavior_changes", "behavioral_invariants"):
        for item in pr_analysis.get(key) or []:
            for w in re.findall(r"[A-Za-z_][A-Za-z0-9_]{3,}", str(item)):
                keys.add(w.lower())
    summary = str((understanding or {}).get("summary") or "")
    for w in re.findall(r"[A-Za-z_][A-Za-z0-9_]{4,}", summary):
        keys.add(w.lower())
    # Def/const names only from diff
    for m in re.finditer(
        r"(?:def|class|async def)\s+([A-Za-z_][A-Za-z0-9_]{2,})",
        diff or "",
    ):
        keys.add(m.group(1).lower())
    return keys


def _format_analysis_for_prompt(pr_analysis: dict) -> str:
    if not pr_analysis:
        return "(no analysis)"
    lines: list[str] = []
    scalar_fields = [
        ("changed_files", "Changed files"),
        ("modified_functions", "Modified functions"),
        ("added_functions", "Added functions"),
        ("constants_added", "Constants added"),
        ("added_test_functions", "Added test functions"),
        ("review_hotspots", "Review hotspots"),
        ("logic_changes", "Logic changes"),
        ("behavior_changes", "Behavior changes"),
        ("behavioral_invariants", "Behavioral invariants"),
        ("design_assumptions", "Design assumptions"),
        ("downstream_impacts", "Downstream impacts"),
        ("architectural_changes", "Architectural changes"),
    ]
    for key, label in scalar_fields:
        val = pr_analysis.get(key)
        if val:
            if isinstance(val, list):
                lines.append(f"{label}:")
                for item in val:
                    lines.append(f"  - {item}")
            else:
                lines.append(f"{label}: {val}")
    return "\n".join(lines) if lines else "(no structured analysis)"


def _build_specialist_context(
    state: dict,
    role_focus: str,
    max_diff_chars: int = 14000,
    max_evidence_chunks: int = 8,
) -> str:
    """
    Order (mandatory):
      A title/body → B understanding → C analysis → D planner
      → E UNIFIED DIFF (primary) → F filtered evidence (secondary) → G role
    """
    title = str(state.get("title") or "")[:200]
    body = str(state.get("body") or "")[:400]

    understanding = state.get("pr_understanding") or {}
    und_summary = ""
    und_risk = ""
    und_types = ""
    verification_from_u: list[str] = []
    if isinstance(understanding, dict):
        und_summary = str(understanding.get("summary") or "")[:500]
        und_risk = str(understanding.get("risk_level") or "")
        und_types = ", ".join(
            str(t) for t in (
                understanding.get("change_types")
                or understanding.get("change_type")
                or []
            )
        )
        verification_from_u = list(understanding.get("verification_targets") or [])[:6]

    analysis = state.get("pr_analysis") or {}
    if not isinstance(analysis, dict):
        analysis = {}
    analysis_block = _format_analysis_for_prompt(analysis)
    pr_symbols = _extract_pr_symbols(analysis)
    files_changed = list(state.get("files_changed") or analysis.get("changed_files") or [])

    plan = state.get("review_plan") or {}
    focus_notes: list[str] = []
    verification_targets: list[str] = list(verification_from_u)
    if isinstance(plan, dict):
        focus_notes = list(plan.get("focus_notes") or [])
        for t in plan.get("verification_targets") or []:
            if t not in verification_targets:
                verification_targets.append(t)

    full_diff = (state.get("full_diff") or "").strip()
    if not full_diff:
        diff_block = (
            "(no unified diff available — you MUST still reason from "
            "title/analysis only; do NOT invent file behavior)"
        )
    else:
        diff_block = full_diff[:max_diff_chars]

    raw_context = str(state.get("context_from_kb") or "")
    filtered_evidence = filter_evidence_for_pr(
        raw_context,
        pr_symbols=pr_symbols,
        diff=full_diff,
        changed_files=files_changed,
        max_chunks=max_evidence_chunks,
    )

    from core.pr_facts import format_pr_facts_for_prompt
    pr_facts = state.get("pr_facts") or {}
    facts_block = format_pr_facts_for_prompt(pr_facts) if pr_facts else ""

    parts: list[str] = [
        f"=== A. PR TITLE ===\n{title}",
        f"=== B. PR BODY (excerpt) ===\n{body}" if body.strip() else "",
        f"=== C. DETERMINISTIC PR FACTS ===\n{facts_block}" if facts_block else "",
        f"""=== D. PR UNDERSTANDING ===
Summary: {und_summary}
Risk: {und_risk}
Change types: {und_types}""",
        f"=== E. PR ANALYSIS (Phase-2 structured facts — trust these) ===\n{analysis_block}",
    ]
    if focus_notes:
        parts.append(
            "=== E. PLANNER FOCUS NOTES ===\n"
            + "\n".join(f"  - {n}" for n in focus_notes[:10])
        )
    if verification_targets:
        parts.append(
            "=== VERIFICATION TARGETS ===\n"
            + "\n".join(f"  - {t}" for t in verification_targets[:8])
        )
    parts.append(f"=== F. UNIFIED DIFF (PRIMARY TRUTH — review THIS) ===\n{diff_block}")
    parts.append(
        "=== G. FILTERED REPO EVIDENCE (SECONDARY — ignore if unrelated to the diff) ===\n"
        + filtered_evidence
    )
    parts.append(f"=== H. YOUR REVIEW ROLE FOCUS ===\n{role_focus.strip()}")

    return "\n\n".join(p for p in parts if p)


def is_pr_relevant_finding(
    finding: dict,
    pr_symbols: set[str],
    pr_keywords: set[str] | None = None,
    diff: str = "",
) -> bool:
    """
    Strict relevance: default FALSE unless anchored on PR symbols/keywords.
    """
    title = (finding.get("title") or "").lower()
    detail = (finding.get("detail") or finding.get("description") or "").lower()
    syms = {str(s).lower() for s in (finding.get("related_symbols") or [])}
    text = f"{title} {detail}"

    # Boilerplate
    if re.search(r"core behavior verified by \w*agent", title):
        return False
    if title.strip() in ("looks good", "no issues", "none", "n/a"):
        return False
    if text.strip().startswith("the provided code snippets"):
        return False

    # Pure documentation of unrelated helpers
    pure_description = re.search(
        r"\b(returns|maps|normalizes|handles|merges|ensures|relativizes|retrieves)\b",
        text,
    )
    risk_language = re.search(
        r"\b(risk|missing|should|equal|unknown|gap|consider|concern|warn|fail|"
        r"incorrect|bug|issue|problem|question|suggest|assert|coverage|edge case|"
        r"invariant|regression|priority|overwrite|collapse)\b",
        text,
    )
    if pure_description and not risk_language:
        return False

    pr_symbols_l = {s.lower() for s in pr_symbols if s and len(str(s)) >= 2}
    keywords = pr_keywords or set()

    # Strong: explicit PR symbol in text or related_symbols
    if any(sym in text for sym in pr_symbols_l):
        return True
    if syms & pr_symbols_l:
        return True

    # Medium: ≥1 strong keyword from analysis/understanding (not generic English)
    hits = sum(1 for k in keywords if len(k) >= 4 and k in text)
    if hits >= 1 and risk_language:
        return True
    if hits >= 2:
        return True

    # verified findings: allow if summary-like and mentions change/fix/test
    sev = str(finding.get("severity") or "").lower()
    if sev == "verified" and re.search(
        r"\b(fix|priority|collapse|overwrite|test|regression|behavior|correct)\b",
        text,
    ):
        return True

    # Default: drop (this was the main bug — previously returned True)
    return False


# ── Specialist prompts ───────────────────────────────────────────────────────

_SHARED_SYSTEM_RULES = """
You are reviewing THIS PULL REQUEST as a senior engineer — not documenting a codebase.

GROUNDING RULES:
1. Prefer the Change inventory and PR diff excerpt over generic repository knowledge.
2. If classification is dependency/lockfile-only, only discuss dependency/lockfile effects.
3. Every finding must cite at least one concrete path from Changed files or a diff hunk.
4. If evidence is insufficient, say Uncertain — do not invent features.
5. Graphify structure is supporting context, not a license to rewrite the PR purpose.

files_changed is the only allowed evidence universe.
Set finding.file to the path the claim is about.
Do not cite wordlist.txt, .gitignore, LICENSE unless the claim is about that file.
If you discuss sqlserver_loader.py, evidence must be that path (or another changed source file you actually analyzed).

STRUCTURED FINDING RULES:
Each finding MUST look like:
  file, start_line, end_line, symbol, claim, evidence[], reasoning, recommendation, confidence
- file: one path from files_changed (the file the claim is about)
- evidence: that same path (and optional extra related changed paths)
- claim: one sentence, testable
- symbol: only an identifier that appears in the diff or in that file — not a story
Never cite .gitignore or wordlist.txt unless the finding is about that file.
If you cannot fill file from the real change list, return no finding.
Do not finalize "this is a bug" when you only have the first Graphify blob.
If you need callers, neighbors, or a finally/close path, set needs_investigation=true
and question to a concrete ask (e.g. "who calls connect and is there a close/finally?").

PRIMARY source of truth: UNIFIED DIFF (section F) + Phase-2 analysis (section E).
SECONDARY: filtered evidence (section G). If a chunk is unrelated to the diff, IGNORE IT.

FORBIDDEN (will be discarded):
- Explaining functions the DIFF does not change (e.g. path helpers, unrelated utilities)
- Findings that only restate "function X does Y"
- severity=concern for neutral descriptions with no risk
- Summaries starting with "The provided code snippets…"
- Inventing files, APIs, or behaviors not in the diff/analysis

REQUIRED structure:
1) summary: 2–4 sentences about THIS PR's behavioral/logic change only
2) findings: mix of:
   - verified: confirm the intended fix/behavior if the diff supports it
   - concern / question / suggestion: edge cases of THIS change (not random modules)
   - blocking: only if you can point to concrete incorrect behavior in the DIFF
3) Every finding.detail MUST answer: "How does this relate to what this PR changed?"
4) assumptions_noted / residual_risks: only about THIS change

If the diff is empty, say so in summary and avoid inventing review points.
Return a SpecialistReview matching the schema.
"""

_CORRECTNESS_ROLE_FOCUS = """
CORRECTNESS reviewer — judge whether THIS PR's change is behaviorally correct.

You MUST try to cover (when applicable to the diff):
- Whether the stated bug/feature is actually fixed/implemented in the changed lines
- Edge cases: equal priority / ties, unknown values, empty inputs, order dependence
- Invariants and overwrite/merge semantics if the PR changes them
- Failure paths and backward compatibility of the new behavior
- Residual correctness risks that a maintainer should still verify

Do NOT document unrelated helpers in the same file.
Prefer concern/question over fabricating a definite bug when evidence is incomplete.
"""

_CODE_QUALITY_ROLE_FOCUS = """
CODE QUALITY reviewer — judge maintainability of THE CHANGED CODE only.

You MUST try to cover (when applicable to the diff):
- Hardcoded tables/config vs extensibility of what the PR introduced
- Naming, comments, and documentation of new policy/behavior
- Duplication, coupling, and abstraction of modified code
- Clarity of error handling / types on new paths

Do NOT write a tour of pre-existing helpers the PR did not touch.
Nits are fine; do not inflate them to concern without a real maintainability issue.
"""

_TESTING_ROLE_FOCUS = """
TESTING reviewer — judge test coverage for THIS PR's change only.

You MUST try to cover:
- What the new/changed tests actually assert (behavior, not "file exists")
- Gaps: untested edge cases implied by the PR (ties, unknown values, order, errors)
- Whether regression risk is adequately locked down

Deterministic signals are provided above the context block.
Do NOT report unrelated existing tests as concerns.
"""


def correctness_agent(state: ReviewState) -> dict:
    if not _should_run(state, "correctness"):
        return {
            "correctness_findings": [],
            "correctness_meta": {"skipped": True, "raw": 0, "grounded": 0},
            "traces": [{"agent": "CorrectnessAgent", "output": "skipped (not in review_plan)"}],
        }

    files_changed = list(state.get("files_changed") or [])
    diff = _diff_for_review(state)

    context_block = _build_specialist_context(
        state,
        role_focus=_CORRECTNESS_ROLE_FOCUS,
        max_diff_chars=14000,
        max_evidence_chunks=8,
    )

    prompt = ChatPromptTemplate.from_messages([
        ("system", _SHARED_SYSTEM_RULES.strip()),
        ("human", "{context_block}\n\nReturn SpecialistReview."),
    ]).format(context_block=context_block)

    try:
        review = gateway.generate_structured(
            prompt=prompt,
            schema=SpecialistReview,
            capability="correctness_review",
            agent_name="CorrectnessAgent",
            temperature=0.1,
            max_tokens=2000,
        )
    except Exception:
        review = SpecialistReview(
            summary="CorrectnessAgent: LLM call failed; manual review required.",
            findings=[],
            no_blocking_issues=False,
        )

    if not isinstance(review, SpecialistReview):
        review = SpecialistReview(**(review if isinstance(review, dict) else {}))

    review = ensure_review_substance(review, "CorrectnessAgent")
    review = _ground_specialist_review(
        review,
        files_changed=files_changed,
        context_from_kb=diff,
        category="correctness",
        id_prefix="corr",
    )

    finding_dicts = []
    for i, f in enumerate(review.findings):
        fd = _finding_to_dict(f)
        fd["id"] = f"corr-{i}"
        fd["category"] = "correctness"
        finding_dicts.append(fd)

    meta = {
        "skipped": False,
        "raw": len(review.findings),
        "grounded": len(finding_dicts),
        "dropped_irrelevant": 0,
        "summary": review.summary,
        "no_blocking_issues": review.no_blocking_issues,
        "assumptions": review.assumptions_noted,
        "residual_risks": review.residual_risks,
    }

    return {
        "correctness_review": review.model_dump(),
        "correctness_findings": finding_dicts,
        "correctness_meta": meta,
        "traces": [{
            "agent": "CorrectnessAgent",
            "output": (
                f"raw={meta['raw']} grounded={meta['grounded']} "
                f"summary={review.summary[:120]}"
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

    files_changed = list(state.get("files_changed") or [])
    diff = _diff_for_review(state, max_chars=10000)

    context_block = _build_specialist_context(
        state,
        role_focus=_CODE_QUALITY_ROLE_FOCUS,
        max_diff_chars=10000,
        max_evidence_chunks=6,
    )

    prompt = ChatPromptTemplate.from_messages([
        ("system", _SHARED_SYSTEM_RULES.strip()),
        ("human", "{context_block}\n\nReturn SpecialistReview."),
    ]).format(context_block=context_block)

    try:
        review = gateway.generate_structured(
            prompt=prompt,
            schema=SpecialistReview,
            capability="code_quality_review",
            agent_name="CodeQualityAgent",
            temperature=0.15,
            max_tokens=2000,
        )
    except Exception:
        review = SpecialistReview(
            summary="CodeQualityAgent: LLM call failed; manual review required.",
            findings=[],
            no_blocking_issues=False,
        )

    if not isinstance(review, SpecialistReview):
        review = SpecialistReview(**(review if isinstance(review, dict) else {}))

    review = ensure_review_substance(review, "CodeQualityAgent")
    review = _ground_specialist_review(
        review,
        files_changed=files_changed,
        context_from_kb=diff,
        category="code_quality",
        id_prefix="qual",
    )

    finding_dicts = []
    for i, f in enumerate(review.findings):
        fd = _finding_to_dict(f)
        fd["id"] = f"qual-{i}"
        fd["category"] = "code_quality"
        finding_dicts.append(fd)

    meta = {
        "skipped": False,
        "raw": len(review.findings),
        "grounded": len(finding_dicts),
        "dropped_irrelevant": 0,
        "summary": review.summary,
        "no_blocking_issues": review.no_blocking_issues,
        "assumptions": review.assumptions_noted,
        "residual_risks": review.residual_risks,
    }

    return {
        "quality_review": review.model_dump(),
        "quality_findings": finding_dicts,
        "quality_meta": meta,
        "traces": [{
            "agent": "CodeQualityAgent",
            "output": (
                f"raw={meta['raw']} grounded={meta['grounded']} "
                f"summary={review.summary[:120]}"
            ),
        }],
    }


def testing_agent(state: ReviewState) -> dict:
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

    pr_analysis = state.get("pr_analysis") or {}
    if not isinstance(pr_analysis, dict):
        pr_analysis = {}
    files_changed = list(state.get("files_changed") or [])
    diff = _diff_for_review(state, max_chars=10000)

    tests_touched = any(
        "test" in str(f).lower() or str(f).endswith("_test.py")
        for f in files_changed
    )
    analysis_tests = bool(pr_analysis.get("tests_added_or_modified"))

    context_block = _build_specialist_context(
        state,
        role_focus=_TESTING_ROLE_FOCUS,
        max_diff_chars=10000,
        max_evidence_chunks=8,
    )
    context_block = (
        f"Deterministic signals:\n"
        f"  - tests_in_changed_files: {tests_touched}\n"
        f"  - analysis.tests_added_or_modified: {analysis_tests}\n\n"
        + context_block
    )

    prompt = ChatPromptTemplate.from_messages([
        ("system", _SHARED_SYSTEM_RULES.strip()),
        ("human", "{context_block}\n\nReturn SpecialistReview."),
    ]).format(context_block=context_block)

    try:
        review = gateway.generate_structured(
            prompt=prompt,
            schema=SpecialistReview,
            capability="reasoning",
            agent_name="TestingAgent",
            temperature=0.15,
            max_tokens=2000,
        )
    except Exception:
        review = SpecialistReview(
            summary="TestingAgent: LLM call failed; manual review required.",
            findings=[],
            no_blocking_issues=False,
        )

    if not isinstance(review, SpecialistReview):
        review = SpecialistReview(**(review if isinstance(review, dict) else {}))

    review = ensure_review_substance(review, "TestingAgent")
    review = _ground_specialist_review(
        review,
        files_changed=files_changed,
        context_from_kb=diff,
        category="testing",
        id_prefix="test",
    )

    finding_dicts = []
    for i, f in enumerate(review.findings):
        fd = _finding_to_dict(f)
        fd["id"] = f"test-{i}"
        fd["category"] = "testing"
        finding_dicts.append(fd)

    meta = {
        "skipped": False,
        "raw": len(review.findings),
        "grounded": len(finding_dicts),
        "dropped_irrelevant": 0,
        "summary": review.summary,
        "no_blocking_issues": review.no_blocking_issues,
        "assumptions": review.assumptions_noted,
        "residual_risks": review.residual_risks,
        "tests_touched": tests_touched,
    }

    return {
        "testing_review": review.model_dump(),
        "testing_findings": finding_dicts,
        "testing_meta": meta,
        "traces": [{
            "agent": "TestingAgent",
            "output": (
                f"raw={meta['raw']} grounded={meta['grounded']} "
                f"tests_touched={tests_touched} "
                f"summary={review.summary[:120]}"
            ),
        }],
    }


# ── Evidence package (plan-driven) ───────────────────────────────────────────

# ── Evidence package (Graphify-only) ─────────────────────────────────────────

def build_evidence_package(state: dict) -> dict:
    """
    Build review evidence from Graphify only.
    No Qdrant. No Neo4j. No second vector client.
    """
    from core.graphify_retriever import GraphifyRetriever
    from core.repository_knowledge.structural import graph_available

    repo = state["repo"]
    files_changed = list(state.get("files_changed") or [])
    title = state.get("title") or ""
    body = state.get("body") or ""
    understanding = state.get("pr_understanding") or {}

    plan_raw = state.get("review_plan") or {}
    try:
        plan = ReviewPlan.model_validate(plan_raw) if plan_raw else None
    except Exception:
        plan = None

    if not graph_available(repo):
        msg = (
            f"Graphify graph not found for {repo}. "
            f"Run: cd repos/{repo.replace('/', '_')} && graphify . --code-only"
        )
        return {
            "evidence_package": None,
            "context_from_kb": msg,
            "traces": [{
                "agent": "BuildEvidencePackage",
                "output": "graphify_missing",
            }],
        }

    retriever = GraphifyRetriever(repo)

    from core.pr_facts import (
        question_grounded_in_pr,
        dedupe_near_duplicate_questions,
    )

    diff = state.get("full_diff") or ""
    files = list(files_changed or [])

    grounded_qs: list[str] = []
    if plan and getattr(plan, "retrieval_questions", None):
        for q in plan.retrieval_questions[:10]:
            if isinstance(q, dict):
                try:
                    q = RetrievalQuestion.model_validate(q)
                except Exception:
                    continue
            question = getattr(q, "question", None) or str(q)
            if not question or not str(question).strip():
                continue
            if question_grounded_in_pr(str(question), files, diff):
                grounded_qs.append(str(question).strip())

    grounded_qs = dedupe_near_duplicate_questions(grounded_qs)

    excerpt = (diff or "")[:4000]
    query_parts = [
        title or "",
        "Changed files: " + ", ".join(files[:40]),
        excerpt,
    ]
    if grounded_qs:
        query_parts.append(
            "Retrieval focus:\n" + "\n".join(f"- {q}" for q in grounded_qs[:4])
        )
    query = "\n".join(p for p in query_parts if p).strip() or (
        "what related modules and call relationships matter for this change?"
    )

    # One Graphify retrieve: title + files_changed + diff excerpt (+ grounded questions)
    docs = retriever.retrieve(
        query,
        k=8,
        pr_title=title,
        pr_body=body,
        files_changed=files_changed,
        full_diff=diff,
        pr_number=state.get("number") or state.get("pr_number"),
    )

    seen = set()
    unique_docs = []
    for d in docs:
        key = (d.page_content or "")[:240]
        if key in seen:
            continue
        seen.add(key)
        unique_docs.append(d)

    rich_context = "\n\n---\n\n".join(
        d.page_content for d in unique_docs if d.page_content
    ).strip()

    # Keep evidence_package compatible with downstream if it only needs text-ish data.
    # If your EvidencePackage is required as a real object, map into it below.
    evidence_package = _graphify_docs_to_evidence_package(
        unique_docs,
        repo=repo,
        files_changed=files_changed,
        understanding=understanding if isinstance(understanding, dict) else {},
    )

    n_q = len(grounded_qs)
    n_ev = len(unique_docs)

    return {
        "evidence_package": evidence_package,
        "context_from_kb": rich_context,
        "traces": [{
            "agent": "BuildEvidencePackage",
            "output": (
                f"backend=graphify retrieve=1 "
                f"plan_questions_kept={n_q} docs={n_ev}"
            ),
        }],
    }


def _graphify_docs_to_evidence_package(docs, *, repo: str, files_changed, understanding):
    """
    Best-effort adapter.
    Prefer a real EvidencePackage if available; else return a simple namespace/dict.
    """
    try:
        from core.evidence import EvidencePackage, Evidence
        ItemClass = Evidence
    except ImportError:
        try:
            from core.query_engine.types import EvidencePackage, EvidenceItem
            ItemClass = EvidenceItem
        except ImportError:
            class _Item:
                def __init__(self, text, meta):
                    self.text = text
                    self.content = text
                    self.metadata = meta
                    self.source = meta.get("source", "graphify")

            class _Pkg:
                def __init__(self, evidences):
                    self.evidences = evidences
                    self.repo = repo
                    self.files_changed = files_changed
                    self.pr_understanding = understanding

            return _Pkg([
                _Item(d.page_content, dict(d.metadata or {}))
                for d in docs
            ])

    items = []
    for i, d in enumerate(docs):
        text = d.page_content or ""
        meta = dict(d.metadata or {})
        try:
            items.append(
                ItemClass(
                    path=meta.get("path", "structural_context"),
                    content=text,
                    source="graphify",
                    metadata=meta,
                )
            )
        except Exception:
            try:
                items.append(
                    ItemClass(
                        content=text,
                        source="graphify",
                    )
                )
            except Exception:
                continue

    try:
        return EvidencePackage(
            evidences=items,
            query="",
            pr_understanding=understanding if isinstance(understanding, dict) else {},
            affected_files=list(files_changed or []),
        )
    except Exception:
        try:
            return EvidencePackage(evidences=items, query="")
        except Exception:
            class _Pkg:
                def __init__(self, evidences):
                    self.evidences = evidences

            return _Pkg(items)


def _merge_packages(packages, max_items: int = 18):
    if not packages:
        return None
    from core.hybrid_retriever import merge_evidence_packages

    per_query_docs = []
    all_affected = set()
    all_symbols = set()
    for pkg in packages:
        evs = getattr(pkg, "evidences", None) or []
        per_query_docs.append(evs)
        for f in getattr(pkg, "affected_files", None) or []:
            all_affected.add(f)
        for s in getattr(pkg, "related_symbols", None) or []:
            all_symbols.add(s)

    merged = merge_evidence_packages(per_query_docs, max_total=max_items)
    for ev in merged:
        p = getattr(ev, "path", None) or (getattr(ev, "metadata", {}) or {}).get("path")
        if p:
            all_affected.add(p)
        syms = getattr(ev, "symbols", None) or (getattr(ev, "metadata", {}) or {}).get("symbols") or []
        for s in syms:
            all_symbols.add(s)

    head = packages[0]
    try:
        from dataclasses import replace, is_dataclass
        if is_dataclass(head) and hasattr(head, "evidences"):
            return replace(
                head,
                evidences=merged,
                affected_files=sorted(all_affected),
                related_symbols=sorted(all_symbols),
            )
    except Exception:
        pass
    try:
        head.evidences = merged
        if hasattr(head, "count"):
            head.count = len(merged)
        if hasattr(head, "affected_files"):
            head.affected_files = sorted(all_affected)
        if hasattr(head, "related_symbols"):
            head.related_symbols = sorted(all_symbols)
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
    """Rank VALIDATED survivors only. Must not invent findings or revive drops."""
    from core.finding_validator import (
        filter_findings,
        log_validation,
        normalize_findings,
    )
    from core.pr_facts import extract_diff_symbols

    facts = state.get("pr_facts") or {}
    files_changed = list(facts.get("files_changed") or state.get("files_changed") or [])
    paths_in_diff = list(facts.get("paths_in_diff") or [])
    full_diff = state.get("full_diff") or ""
    changed_symbols = extract_diff_symbols(full_diff)
    report = state.get("validation_report") if isinstance(state.get("validation_report"), dict) else None

    if report and report.get("ran"):
        validated_candidates = normalize_findings(
            state.get("validated_findings")
            if state.get("validated_findings") is not None
            else state.get("findings")
            or [],
            files_changed=files_changed,
            pr_facts=facts,
        )
        pre_dropped = list(report.get("dropped_summaries") or [])
        raw_in = report.get("raw", len(validated_candidates))
    else:
        combined = []
        for src, cat in (
            (state.get("correctness_findings") or [], "correctness"),
            (state.get("quality_findings") or [], "code_quality"),
            (state.get("testing_findings") or [], "testing"),
        ):
            for f in src:
                d = _finding_to_dict(f)
                d["category"] = d.get("category") or cat
                combined.append(d)
        normalized = normalize_findings(
            combined, files_changed=files_changed, pr_facts=facts
        )
        val_res = filter_findings(
            normalized,
            files_changed=files_changed,
            paths_in_diff=paths_in_diff,
            changed_symbols=changed_symbols,
            full_diff=full_diff,
        )
        val_res["raw"] = len(normalized)
        log_validation(val_res)
        validated_candidates = val_res["kept"]
        pre_dropped = [
            {
                "title": (item.get("finding") or {}).get("title"),
                "reason": item.get("reason"),
                "file": (item.get("finding") or {}).get("file"),
                "evidence": (item.get("finding") or {}).get("evidence"),
            }
            for item in val_res["dropped"]
        ]
        raw_in = len(normalized)

    if not validated_candidates:
        notes = "no validated findings"
        return {
            "findings": [],
            "validated_findings": [],
            "critique": {
                "kept": [],
                "dropped": pre_dropped,
                "notes": notes,
            },
            "traces": [{"agent": "CriticAgent", "output": notes}],
        }

    prompt = ChatPromptTemplate.from_messages([
        ("system", """You are a strict PR review critic (reasoning gate), NOT a second code reviewer.

Rules:
- You only rank VALIDATED findings.
- Do not restore findings the validator rejected.
- If kept is empty, say there are no validated findings and do not invent new issues.
- verification_status is computed from the diff hunks, not from you.
- Only supported findings may be treated as blocking.
- Uncertain findings are COMMENT-grade only.
- Unsupported findings cannot justify REQUEST_CHANGES.
- PRESERVE high-signal specialist findings: verified behavior, real concerns, questions, suggestions.
- DROP documentation-only findings and claims unrelated to the PR change.
- MERGE near-duplicates into one tighter finding.
- Do NOT invent new findings.
- Keep each finding.file / evidence pointing at a path from files_changed.

Return Findings: the final kept list only."""),
        ("human", """PR title: {title}

VALIDATED findings (the only candidates you may rank):
{candidates}

Return only the findings to KEEP. Do not add new ones."""),
    ]).format(
        title=state.get("title", ""),
        candidates=json.dumps(validated_candidates, indent=2)[:8000],
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
        val_post = filter_findings(
            normalize_findings(
                [_finding_to_dict(f) for f in llm_findings],
                files_changed=files_changed,
                pr_facts=facts,
            ),
            files_changed=files_changed,
            paths_in_diff=paths_in_diff,
            changed_symbols=changed_symbols,
            full_diff=full_diff,
        )
        kept = val_post["kept"]
        if not kept and validated_candidates:
            kept = validated_candidates
    except Exception:
        kept = validated_candidates

    from core.verification.policy import reattach_stamps

    kept = reattach_stamps(kept, validated_candidates)

    critique = {
        "kept": kept,
        "dropped": pre_dropped,
        "notes": f"in={raw_in} validated={len(validated_candidates)} kept={len(kept)}",
    }

    return {
        "findings": kept,
        "validated_findings": kept,
        "critique": critique,
        "traces": [{
            "agent": "CriticAgent",
            "output": critique["notes"],
        }],
    }


# ── Final decision ───────────────────────────────────────────────────────────

def final_recommender(state: ReviewState) -> dict:
    findings = list(
        state.get("validated_findings")
        if state.get("validated_findings") is not None
        else state.get("findings")
        or []
    )
    finding_dicts = [_finding_to_dict(f) for f in findings]
    understanding = state.get("pr_understanding") or {}
    risk = understanding.get("risk_level", "medium") if isinstance(understanding, dict) else "medium"
    summary_u = understanding.get("summary", "") if isinstance(understanding, dict) else ""

    plan = state.get("review_plan") or {}
    plan_risk = plan.get("risk_level") if isinstance(plan, dict) else ""
    _rank = {"low": 0, "medium": 1, "high": 2, "critical": 3}
    if _rank.get(str(plan_risk).lower(), -1) > _rank.get(str(risk).lower(), 0):
        risk = plan_risk

    empty = not finding_dicts
    classification = str((state.get("pr_facts") or {}).get("classification") or "")
    from core.verification.policy import clamp_recommendation, recommendation_from_verification

    vrep = state.get("verification_report") if isinstance(state.get("verification_report"), dict) else {}
    exrep = state.get("execution_report") if isinstance(state.get("execution_report"), dict) else {}
    if vrep.get("ran") or any(f.get("verification_status") for f in finding_dicts) or exrep:
        baseline = recommendation_from_verification(
            finding_dicts,
            classification=classification,
            risk=str(risk or "medium"),
            execution=exrep or None,
        )
    else:
        sev = [str(f.get("severity", "low")).lower() for f in finding_dicts]
        if any(s in ("critical", "high", "blocking") for s in sev):
            baseline = "REQUEST_CHANGES"
        elif any(s in ("medium", "concern") for s in sev):
            baseline = "COMMENT"
        elif empty and classification == "lockfile-only":
            baseline = "COMMENT"
        elif empty and str(risk).lower() in ("medium", "high", "critical"):
            baseline = "COMMENT"
        else:
            baseline = "MERGE"
    if empty:
        corr_summary = test_summary = qual_summary = (
            "(omitted — no validated findings; do not recap unvalidated specialist drafts)"
        )
        findings_json = "(none)"
    else:
        corr_meta = state.get("correctness_meta") or {}
        test_meta = state.get("testing_meta") or {}
        qual_meta = state.get("quality_meta") or {}
        corr_summary = corr_meta.get("summary", "")
        test_summary = test_meta.get("summary", "")
        qual_summary = qual_meta.get("summary", "")
        findings_json = json.dumps(finding_dicts, indent=2)[:6000]

    uncertain = []
    for h in state.get("hypotheses") or []:
        d = h if isinstance(h, dict) else (h.model_dump() if hasattr(h, "model_dump") else {})
        if d.get("status") == "uncertain":
            uncertain.append(
                f"{d.get('id')}: {d.get('claim') or d.get('title')} ({d.get('file')})"
            )
    uncertain_block = "\n".join(uncertain) if uncertain else "(none)"

    prompt = ChatPromptTemplate.from_messages([
        ("system", """You are the final maintainer decision.

You may only use VALIDATED findings.
If the list is empty, say there are no validated findings.
Do not restate dropped or ungrounded claims.

Rules:
- recommendation MUST be MERGE | REQUEST_CHANGES | COMMENT
- summary MUST only use: PR understanding summary + VALIDATED findings
- If VALIDATED findings is empty, MERGE is allowed only as "no validated issues found" — not as a recap of rejected nits.
- If the list is empty AND risk is medium/high, prefer COMMENT over MERGE (could not confirm issues, not high confidence merge).
- If classification is lockfile-only AND validated findings is empty, prefer COMMENT ("lockfile-only; no grounded issue"), not MERGE.
- Uncertain investigation hypotheses may be mentioned only as "could not confirm X" — not as proven bugs.
- verification_status: only supported findings with severity >= medium may justify REQUEST_CHANGES.
- Uncertain = COMMENT-grade. Unsupported cannot REQUEST_CHANGES.
- Do NOT invent features, bugs, or subsystems not present there
- Blocking / critical issues → REQUEST_CHANGES
- Concerns / questions / suggestions without blocking bugs → MERGE or COMMENT depending on risk"""),
        ("human", """Understanding summary: {summary_u}
Risk: {risk}
Baseline: {baseline}
Correctness summary: {corr_summary}
Testing summary: {test_summary}
Quality summary: {qual_summary}

VALIDATED findings (the ONLY issues you may mention):
{findings}

Uncertain investigation hypotheses (mention only as unconfirmed):
{uncertain}

Return ReviewOutput."""),
    ]).format(
        summary_u=summary_u,
        risk=risk,
        baseline=baseline,
        corr_summary=corr_summary,
        test_summary=test_summary,
        qual_summary=qual_summary,
        findings=findings_json,
        uncertain=uncertain_block,
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
        summary = getattr(response, "summary", None) or ""
        confidence = float(getattr(response, "confidence", None) or 0.6)
    except Exception:
        rec = baseline
        if empty:
            summary = "No validated findings."
        else:
            summary = f"Automated decision based on {len(finding_dicts)} kept findings."
        confidence = 0.55

    rec = clamp_recommendation(rec, baseline, classification)

    blocking = [
        f.get("title")
        for f in finding_dicts
        if f.get("verification_status") == "supported"
        and str(f.get("severity", "")).lower() in ("high", "critical", "blocking", "medium", "concern")
    ]
    if rec != "REQUEST_CHANGES":
        blocking = []

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