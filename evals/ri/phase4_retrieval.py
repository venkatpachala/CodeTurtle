"""Phase 4: multi-query retrieval against real Qdrant index (EvidencePackage)."""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, List, Set

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from evals.ri.fixtures import fetch_pr, save, load
from evals.ri.report import PhaseReport
from core.knowledge_base import KnowledgeBase
from core.hybrid_retriever import HybridRetriever


def _question_text(q: Any) -> str:
    if isinstance(q, dict):
        return str(q.get("question") or q.get("q") or "").strip()
    return str(q or "").strip()


def _path_from_evidence(e: Any) -> str | None:
    """Normalize one evidence item → repo-relative path if possible."""
    if e is None:
        return None
    if isinstance(e, str):
        return e
    # Pydantic / object
    for attr in ("path", "file_path", "filepath"):
        if hasattr(e, attr) and getattr(e, attr):
            return str(getattr(e, attr))
    meta = getattr(e, "metadata", None)
    if isinstance(meta, dict) and meta.get("path"):
        return str(meta["path"])
    if isinstance(e, dict):
        if e.get("path"):
            return str(e["path"])
        m = e.get("metadata") or {}
        if isinstance(m, dict) and m.get("path"):
            return str(m["path"])
    return None


def _paths_from_package(pkg: Any) -> tuple[int, List[str], List[str], str]:
    """
    Returns:
      n_evidences, evidence_paths, affected_files, summary
    """
    if pkg is None:
        return 0, [], [], ""

    evidences = list(getattr(pkg, "evidences", None) or [])
    n = len(evidences)

    paths: List[str] = []
    for e in evidences:
        p = _path_from_evidence(e)
        if p:
            paths.append(p)

    affected = list(getattr(pkg, "affected_files", None) or [])
    affected = [str(x) for x in affected if x]

    summary = str(getattr(pkg, "summary", None) or "")

    return n, paths, affected, summary


def evaluate(repo: str, number: int) -> PhaseReport:
    state = fetch_pr(repo, number)

    # Prefer planner questions from phase 3
    questions: list = []
    try:
        plan = load(repo, number, "03_plan.json").get("output") or {}
        questions = plan.get("retrieval_questions") or []
    except FileNotFoundError:
        plan = {}

    if not questions:
        questions = [state.get("title") or "repository code"]

    try:
        understanding = load(repo, number, "01_understanding.json").get("output") or {}
    except FileNotFoundError:
        understanding = {}

    collection = repo.replace("/", "_")
    kb = KnowledgeBase(collection)
    retriever = HybridRetriever(repo, kb=kb)

    files_changed = [p.replace("\\", "/").lstrip("./") for p in state.get("files_changed", [])]
    full_diff = state.get("patch") or state.get("diff") or ""

    all_paths: Set[str] = set()
    all_affected: Set[str] = set()
    per_q: list[dict] = []
    raw_packages: list[Any] = []

    for q in questions:
        qtext = _question_text(q)
        if not qtext:
            continue

        prefer_paths = []
        prefer_symbols = []
        if isinstance(q, dict):
            prefer_paths = q.get("prefer_paths") or []
            prefer_symbols = q.get("prefer_symbols") or []
        elif hasattr(q, "prefer_paths"):
            prefer_paths = getattr(q, "prefer_paths", []) or []
            prefer_symbols = getattr(q, "prefer_symbols", []) or []

        try:
            pkg = retriever.retrieve(
                query=qtext,
                pr_understanding=understanding or state.get("pr_understanding") or {},
                files_changed=files_changed,
                prefer_paths=prefer_paths or files_changed,
                prefer_symbols=prefer_symbols,
                full_diff=full_diff,
                k=6,
            )
        except TypeError:
            pkg = retriever.retrieve(query=qtext, k=6)

        raw_packages.append(pkg)
        n, paths, affected, summary = _paths_from_package(pkg)
        symbols = list(getattr(pkg, "related_symbols", None) or []) if pkg is not None else []

        per_q.append({
            "query": qtext[:160],
            "n_evidences": n,
            "paths": paths,
            "affected_files": affected,
            "related_symbols": [str(s) for s in symbols][:20],
            "summary_preview": summary[:240] if summary else "",
        })
        all_paths.update(paths)
        all_affected.update(affected)
        all_paths.update(affected)

    from core.hybrid_retriever import merge_evidence_packages
    per_query_docs = [getattr(p, "evidences", []) for p in raw_packages]
    merged_docs = merge_evidence_packages(per_query_docs, max_total=18)
    merged_paths = [getattr(d, "path", None) or (getattr(d, "metadata", {}) or {}).get("path") for d in merged_docs]
    merged_paths = [p for p in merged_paths if p]

    save(
        repo,
        number,
        "04_evidence.json",
        {
            "per_query": per_q,
            "merged_count": len(merged_docs),
            "merged_paths": sorted(set(merged_paths)),
            "all_paths": sorted(all_paths),
            "all_affected_files": sorted(all_affected),
            "files_changed": state["files_changed"],
            "n_questions": len(per_q),
        },
    )

    r = PhaseReport("Phase4 Retrieval")
    total = sum(x["n_evidences"] for x in per_q)
    r.add("retrieved_something", total > 0, f"total_evidences={total}")
    r.add(
        "query_count_matches_plan",
        len(per_q) == len([_question_text(q) for q in questions if _question_text(q)]),
        f"ran={len(per_q)} plan_qs={len(questions)}",
    )

    changed = set(files_changed)
    hit_direct = bool(all_paths & changed)

    # Strict target file check
    target_hit = any(any(c in p for c in changed) for p in all_paths)
    r.add(
        "changed_files_in_evidence",
        target_hit,
        f"changed={sorted(changed)} found_sample={sorted(all_paths)[:10]}",
    )

    # Distractor check (install.py vs build.py)
    distractors = [p for p in all_paths if "install.py" in p and not any("install.py" in c for c in changed)]
    r.add(
        "distractors_not_dominating",
        len(distractors) <= len(all_paths) * 0.4,
        f"distractors={distractors} total_unique_paths={len(all_paths)}",
    )

    r.add(
        "global_dedupe_capped",
        len(merged_docs) <= 20 and len(merged_docs) > 0,
        f"merged_total={len(merged_docs)} max_cap=20 unique_paths={len(set(merged_paths))}",
    )

    r.add(
        "paths_relevant_to_pr",
        hit_direct or target_hit or total == 0,
        f"direct={hit_direct} sample={sorted(all_paths)[:12]}",
    )
    r.add(
        "package_has_affected_or_paths",
        bool(all_paths) or total == 0,
        f"paths={len(all_paths)} affected={len(all_affected)}",
    )

    r.print()
    return r


if __name__ == "__main__":
    repo = sys.argv[1] if len(sys.argv) > 1 else "Graphify-Labs/graphify"
    number = int(sys.argv[2]) if len(sys.argv) > 2 else 2400
    evaluate(repo, number)