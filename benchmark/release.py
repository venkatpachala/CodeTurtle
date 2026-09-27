"""Release gate over immutable, explicitly adjudicated paired outcomes.

Input: {dataset_sha256, scorer_version, adjudicated: true, cases: {case_id:
{confirmed_issue_ids, fp, known_buggy, decision, health, latency_seconds}}}.
This does not manufacture adjudications or substitute text overlap for proof.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from benchmark.product_metrics import compare_regressions
from core.review.artifacts import write_json_atomic


def evaluate_paired_release(baseline: dict, candidate: dict) -> dict:
    reasons = []
    for field in ("dataset_sha256", "scorer_version"):
        if not baseline.get(field) or baseline.get(field) != candidate.get(field):
            reasons.append(f"{field}_mismatch")
    if baseline.get("adjudicated") is not True or candidate.get("adjudicated") is not True:
        reasons.append("missing_adjudication")
    old, new = baseline.get("cases") or {}, candidate.get("cases") or {}
    if not old or not new:
        reasons.append("empty_cases")
    if candidate.get("reviewer_dirty") is not False or not candidate.get("reviewer_commit"):
        reasons.append("reviewer_not_frozen")
    comparison = compare_regressions(old, new)
    return {"passed": not reasons and comparison["passed"], "eligibility_errors": reasons,
            "comparison": comparison,
            "scope": "paired regression gate; fresh held-out quality evidence is required separately"}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("baseline", type=Path)
    parser.add_argument("candidate", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = evaluate_paired_release(json.loads(args.baseline.read_text(encoding="utf-8")),
                                    json.loads(args.candidate.read_text(encoding="utf-8")))
    write_json_atomic(args.output, report)
    print("PASS" if report["passed"] else "FAIL")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
