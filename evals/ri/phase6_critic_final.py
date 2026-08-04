"""Phase 6: Critic reasoning gate and final recommender evaluation."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from evals.ri.fixtures import fetch_pr, save, load
from evals.ri.report import PhaseReport
from core.agents import critic_agent, final_recommender


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

    try:
        spec = load(repo, number, "05_specialists.json")
        for kind in ("correctness", "code_quality", "testing"):
            if kind in spec:
                for k, v in spec[kind].items():
                    state[k] = v
    except FileNotFoundError:
        pass

    # Run Critic
    critic_out = critic_agent(state)
    state["findings"] = critic_out.get("findings") or []
    state["critique"] = critic_out.get("critique") or {}

    # Run Final Recommender
    rec_out = final_recommender(state)
    state["final_comment"] = rec_out.get("final_comment") or ""
    state["recommendation"] = rec_out.get("recommendation") or "MERGE"
    state["merge_decision"] = rec_out.get("merge_decision") or {}

    combined = {
        "critic": critic_out,
        "final_recommendation": rec_out,
    }
    save(repo, number, "06_critic_final.json", combined)

    r = PhaseReport("Phase6 Critic & Final Decision")

    # 1. Critic output invariants
    kept = critic_out.get("findings") or []
    critique_meta = critic_out.get("critique") or {}
    r.add("critic_ran_successfully", "kept" in critique_meta, str(critique_meta.get("notes")))
    r.add("critic_findings_is_list", isinstance(kept, list), f"kept_count={len(kept)}")

    # 2. Recommender invariants
    rec = rec_out.get("recommendation")
    valid_recs = {"MERGE", "REQUEST_CHANGES", "COMMENT"}
    r.add("recommendation_valid_enum", rec in valid_recs, f"recommendation={rec}")

    decision = rec_out.get("merge_decision") or {}
    confidence = decision.get("confidence")
    r.add(
        "confidence_in_range",
        isinstance(confidence, (int, float)) and 0.0 <= confidence <= 1.0,
        f"confidence={confidence}",
    )

    summary = decision.get("summary", "")
    r.add("summary_non_empty", bool(str(summary).strip()), f"summary={summary[:80]}...")

    comment = rec_out.get("final_comment", "")
    r.add("final_comment_structured", f"**{rec}**" in comment, f"comment_preview={comment[:100]}...")

    r.print()
    return r


if __name__ == "__main__":
    repo = sys.argv[1] if len(sys.argv) > 1 else "Graphify-Labs/graphify"
    number = int(sys.argv[2]) if len(sys.argv) > 2 else 2400
    evaluate(repo, number)
