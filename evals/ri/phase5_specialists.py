"""Phase 5: plan-gated specialists + grounding invariants."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from evals.ri.fixtures import fetch_pr, save, load
from evals.ri.report import PhaseReport
from core.knowledge_base import KnowledgeBase
from core.agents import (
    correctness_agent,
    code_quality_agent,
    testing_agent,
)  # adjust


def evaluate(repo: str, number: int) -> PhaseReport:
    state = fetch_pr(repo, number)
    for fname, key in [
        ("01_understanding.json", "pr_understanding"),
        ("02_analysis.json", "pr_analysis"),
        ("03_plan.json", "review_plan"),
    ]:
        state[key] = load(repo, number, fname).get("output") or {}

    # minimal context from phase4 paths
    ev = load(repo, number, "04_evidence.json")
    state["context_from_kb"] = "\n".join(ev.get("all_paths") or [])
    state["kb"] = KnowledgeBase(repo.replace("/", "_"))

    plan_reviewers = [str(x).lower() for x in (state["review_plan"].get("reviewers") or [])]

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
    for kind, (fkey, mkey) in mapping.items():
        out = results[kind]
        meta = out.get(mkey) or {}
        findings = out.get(fkey) or []
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
        r.add(f"{kind}_meta_raw_numeric", isinstance(meta.get("raw"), int), str(meta))
        r.add(f"{kind}_meta_grounded_numeric", isinstance(meta.get("grounded"), int), str(meta))
        bad = [f for f in findings if not (f.get("evidence") if isinstance(f, dict) else True)]
        # findings may be dicts
        for f in findings:
            if isinstance(f, dict) and not f.get("evidence"):
                bad.append(f)
        r.add(f"{kind}_all_grounded_have_evidence", len(bad) == 0, f"bad={len(bad)}")
    r.print()
    return r


if __name__ == "__main__":
    repo = sys.argv[1] if len(sys.argv) > 1 else "Graphify-Labs/graphify"
    number = int(sys.argv[2]) if len(sys.argv) > 2 else 2400
    evaluate(repo, number)