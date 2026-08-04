"""Phase 5: plan-gated specialists + grounding invariants + PR-relevance assertions."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from evals.ri.fixtures import fetch_pr, save, load
from evals.ri.report import PhaseReport
from core.knowledge_base import KnowledgeBase
from core.agents import (
    build_evidence_package,
    correctness_agent,
    code_quality_agent,
    testing_agent,
    _extract_pr_symbols,
)

_PR_REVIEW_KEYWORDS = (
    "priority",
    "collapse",
    "relation",
    "build_from_json",
    "overwrite",
    "undirected",
    "calls",
    "references",
    "_relation_priority",
    "edge collapse",
    "same pair",
    "_same_pair",
)

# Symbols that should NEVER appear as finding subjects unless in the diff
_NOISE_SYMBOLS_EVAL = {
    "_doc_twin_remap",
    "_norm_source_file",
    "_semantic_id_remap",
    "dedupe_nodes",
    "_relativize",
}

# Summary openings that indicate the model defaulted to repo-tour mode
_BAD_SUMMARY_PREFIXES = (
    "the provided code snippets",
    "the provided code",
    "these code snippets",
    "the code snippets",
    "the retrieved",
    "the following code",
)


def _summary_is_doc_tour(summary: str) -> bool:
    """Return True if the summary starts with a known repo-tour opener."""
    s = summary.lower().strip()
    return any(s.startswith(prefix) for prefix in _BAD_SUMMARY_PREFIXES)


def _findings_mention_pr_topics(findings: list[dict], summary: str) -> bool:
    """Return True if at least one finding or the summary touches PR keywords."""
    corpus = summary.lower() + " " + json.dumps(findings).lower()
    return any(kw in corpus for kw in _PR_REVIEW_KEYWORDS)


def _has_noise_symbol_finding(findings: list[dict], diff: str) -> bool:
    """Return True if any finding is about a noise symbol NOT present in the diff."""
    diff_lower = diff.lower()
    for f in findings:
        syms = [str(s).lower() for s in (f.get("related_symbols") or [])]
        title = (f.get("title") or "").lower()
        detail = (f.get("detail") or f.get("description") or "").lower()
        for sym in _NOISE_SYMBOLS_EVAL:
            sym_in_finding = sym in syms or sym in title or sym in detail
            sym_in_diff = sym in diff_lower
            if sym_in_finding and not sym_in_diff:
                return True
    return False


def evaluate(repo: str, number: int) -> PhaseReport:
    state = fetch_pr(repo, number)
    for fname, key in [
        ("01_understanding.json", "pr_understanding"),
        ("02_analysis.json", "pr_analysis"),
        ("03_plan.json", "review_plan"),
    ]:
        try:
            state[key] = load(repo, number, fname).get("output") or {}
        except FileNotFoundError:
            state[key] = {}

    state["kb"] = KnowledgeBase(repo.replace("/", "_"))

    # Build rich evidence package from plan & KB
    try:
        ev_out = build_evidence_package(state)
        state["evidence_package"] = ev_out.get("evidence_package")
        state["context_from_kb"] = ev_out.get("context_from_kb") or ""
    except Exception:
        try:
            ev = load(repo, number, "04_evidence.json")
            state["context_from_kb"] = "\n".join(ev.get("all_paths") or [])
        except Exception:
            state["context_from_kb"] = ""

    plan_reviewers = [str(x).lower() for x in (state.get("review_plan", {}).get("reviewers") or [])]
    if not plan_reviewers:
        plan_reviewers = ["correctness", "code_quality", "testing"]

    results = {
        "correctness": correctness_agent(state),
        "code_quality": code_quality_agent(state),
        "testing": testing_agent(state),
    }
    save(repo, number, "05_specialists.json", results)

    r = PhaseReport("Phase5 Specialists")
    mapping = {
        "correctness": ("correctness_findings", "correctness_meta"),
        "code_quality": ("quality_findings", "quality_meta"),
        "testing": ("testing_findings", "testing_meta"),
    }

    all_findings: list[dict] = []
    all_summaries: list[str] = []
    diff = state.get("full_diff") or ""

    pr_analysis = state.get("pr_analysis") or {}
    pr_symbols = _extract_pr_symbols(pr_analysis if isinstance(pr_analysis, dict) else {})

    for kind, (fkey, mkey) in mapping.items():
        out = results[kind]
        meta = out.get(mkey) or {}
        findings = out.get(fkey) or []
        summary = str(meta.get("summary") or "")
        all_findings.extend(findings)
        all_summaries.append(summary)

        planned = kind in plan_reviewers or (
            kind == "code_quality" and "code_quality" in plan_reviewers
        )
        if not planned:
            r.add(
                f"{kind}_skipped_when_not_planned",
                meta.get("skipped") is True or (meta.get("raw", 0) == 0 and not findings),
                str(meta),
            )
            continue

        # Structural invariants
        r.add(f"{kind}_meta_raw_numeric", isinstance(meta.get("raw"), int), str(meta)[:200])
        r.add(f"{kind}_meta_grounded_numeric", isinstance(meta.get("grounded"), int), str(meta)[:200])

        # Anti-abstention check: FAIL if summary AND findings both empty
        has_substance = bool(findings) or bool(summary.strip())
        r.add(f"{kind}_not_abstained", has_substance, f"raw={meta.get('raw')} summary_len={len(summary)}")

        # ── NEW: Fail if summary is in repo-tour doc mode ──────────────────
        r.add(
            f"{kind}_summary_not_doc_tour",
            not _summary_is_doc_tour(summary),
            f"summary={summary[:100]}",
        )

        # Evidence grounding: grounded findings must cite evidence
        bad = [f for f in findings if isinstance(f, dict) and not (f.get("evidence") or f.get("evidence_paths"))]
        r.add(f"{kind}_all_grounded_have_evidence", len(bad) == 0, f"bad={len(bad)}")

        # ── NEW: Fail if findings contain noise symbols not in the diff ────
        has_noise = _has_noise_symbol_finding(findings, diff)
        r.add(
            f"{kind}_no_noise_symbol_findings",
            not has_noise,
            f"noise_symbols_in_findings={has_noise}",
        )

        # ── NEW: dropped_irrelevant tracked ───────────────────────────────
        dropped = meta.get("dropped_irrelevant", 0)
        r.add(
            f"{kind}_drops_irrelevant_tracked",
            "dropped_irrelevant" in meta,
            f"dropped={dropped}",
        )

    # ── NEW: At least one agent addresses PR topics ───────────────────────
    combined_corpus = " ".join(all_summaries) + " " + json.dumps(all_findings)
    r.add(
        "at_least_one_agent_addresses_pr_topics",
        _findings_mention_pr_topics(all_findings, " ".join(all_summaries)),
        f"pr_keywords_found={[kw for kw in _PR_REVIEW_KEYWORDS if kw in combined_corpus.lower()]}",
    )

    # Positive finding diversity (kept from before but re-keyed)
    has_verified = any(str(f.get("severity", "")).lower() == "verified" for f in all_findings)
    has_exploratory = any(
        str(f.get("severity", "")).lower() in ("concern", "question", "suggestion", "nit", "blocking")
        for f in all_findings
    )
    r.add(
        "specialists_provide_substantive_review",
        has_verified or has_exploratory or len(all_findings) > 0,
        f"verified={has_verified} exploratory={has_exploratory} total={len(all_findings)}",
    )

    # Domain edge-case awareness (PR-specific)
    if repo == "Graphify-Labs/graphify" and number == 2400:
        target_kws = ["priority", "order", "tie", "relation", "calls", "references", "collision", "edge"]
        found_kws = [kw for kw in target_kws if kw in combined_corpus.lower()]
        r.add(
            "testing_edge_case_awareness",
            len(found_kws) >= 2,
            f"found_keywords={found_kws}",
        )

    r.print()
    return r


if __name__ == "__main__":
    repo = sys.argv[1] if len(sys.argv) > 1 else "Graphify-Labs/graphify"
    number = int(sys.argv[2]) if len(sys.argv) > 2 else 2400
    evaluate(repo, number)