"""Phase 3: Review planner output quality."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from evals.ri.fixtures import fetch_pr, save, load
from evals.ri.report import PhaseReport

# Import your actual planner function name
from core.review_intelligence.planner import review_planner_agent

ALLOWED = {
    "correctness", "code_quality", "testing", "security",
    "performance", "documentation", "architecture", "api_compat",
    "concurrency",
}


def evaluate(repo: str, number: int) -> PhaseReport:
    state = fetch_pr(repo, number)
    for name, key in [
        ("01_understanding.json", "pr_understanding"),
        ("02_analysis.json", "pr_analysis"),
    ]:
        try:
            state[key] = load(repo, number, name).get("output") or {}
        except FileNotFoundError:
            state[key] = {}

    out = review_planner_agent(state)
    plan = out.get("review_plan") or {}
    save(repo, number, "03_plan.json", {"output": plan, "raw": out})

    reviewers = [str(x).lower() for x in (plan.get("reviewers") or [])]
    questions = plan.get("retrieval_questions") or []
    r = PhaseReport("Phase3 Review Planner")
    r.add("has_reviewers", len(reviewers) >= 1, str(reviewers))
    r.add(
        "reviewers_allowed",
        all(x in ALLOWED for x in reviewers),
        str(reviewers),
    )
    qtexts = []
    for q in questions:
        if isinstance(q, dict):
            qtexts.append(str(q.get("question") or q.get("q") or ""))
        else:
            qtexts.append(str(q))
    r.add("has_retrieval_questions", any(t.strip() for t in qtexts), f"n={len(qtexts)}")
    code_files = [f for f in state["files_changed"] if not f.lower().endswith(".md")]
    if code_files:
        r.add("code_pr_includes_correctness", "correctness" in reviewers, str(reviewers))
    if any("test" in f.lower() for f in state["files_changed"]):
        r.add("test_paths_prefer_testing", "testing" in reviewers, str(reviewers))
    risk = str(plan.get("risk_level") or "").lower()
    r.add("risk_present", risk in {"low", "medium", "high", "critical"}, risk)
    r.print()
    return r


if __name__ == "__main__":
    repo = sys.argv[1] if len(sys.argv) > 1 else "Graphify-Labs/graphify"
    number = int(sys.argv[2]) if len(sys.argv) > 2 else 2400
    evaluate(repo, number)