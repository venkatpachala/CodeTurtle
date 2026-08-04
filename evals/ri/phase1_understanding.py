"""Phase 1: real PRUnderstandingAgent output."""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from evals.ri.fixtures import fetch_pr, save
from evals.ri.report import PhaseReport
from core.pr_understanding import pr_understanding_agent  # adjust import if needed


def _tokens(s: str) -> set[str]:
    return {t.lower() for t in re.findall(r"[a-zA-Z]{4,}", s or "")}


def evaluate(repo: str, number: int) -> PhaseReport:
    state = fetch_pr(repo, number)
    out = pr_understanding_agent(state)
    understanding = out.get("pr_understanding") or {}
    save(repo, number, "01_understanding.json", {
        "input": {
            "title": state["title"],
            "body": (state["body"] or "")[:500],
            "files": state["files_changed"],
        },
        "output": understanding,
        "raw_agent_return": out,
    })

    r = PhaseReport("Phase1 PR Understanding")
    r.add("has_summary", bool(str(understanding.get("summary") or "").strip()))
    risk = str(understanding.get("risk_level") or "").lower()
    r.add("risk_valid", risk in {"low", "medium", "high", "critical"}, risk)
    types = understanding.get("change_type") or understanding.get("change_types") or []
    focus = understanding.get("focus_areas") or []
    r.add("has_change_or_focus", bool(types) or bool(focus), f"types={types} focus={focus}")
    summary = str(understanding.get("summary") or "")
    r.add("summary_long_enough", len(summary) >= 40, f"len={len(summary)}")
    overlap = _tokens(summary) & (_tokens(state["title"]) | _tokens(state["body"]))
    r.add("token_overlap_with_pr", len(overlap) >= 1, f"overlap={sorted(list(overlap))[:8]}")
    r.print()
    return r


if __name__ == "__main__":
    repo = sys.argv[1] if len(sys.argv) > 1 else "Graphify-Labs/graphify"
    number = int(sys.argv[2]) if len(sys.argv) > 2 else 2400
    evaluate(repo, number)