"""Additional product metrics and paired regressions, with explicit denominators."""
from __future__ import annotations

from typing import Any


def measurement(numerator: int, denominator: int) -> dict:
    return {"numerator": numerator, "denominator": denominator,
            "value": numerator / denominator if denominator else None}


def product_metrics(predictions: list[dict]) -> dict[str, Any]:
    completed = abstained = failed = anchored = findings = delivered = delivery_eligible = 0
    for prediction in predictions:
        result = prediction.get("result") or prediction
        status = (result.get("health") or {}).get("status")
        completed += int(status == "completed")
        failed += int(status == "failed")
        reasons = set(result.get("policy_reasons") or [])
        abstained += int(result.get("decision") is None or status != "completed" or bool(reasons & {
            "partial_analysis", "insufficient_inspection", "unresolved_hypotheses",
            "execution_unattributed", "execution_inconclusive", "no_eligible_units"}))
        published = (prediction.get("publication") or {}).get("status") in {"published", "already_published"}
        plan = prediction.get("publication_preview") or {}
        product = result.get("product_findings") or []
        findings += len(product)
        anchored += len(plan.get("comments") or [])
        delivered += len(product) if published else 0
        if (prediction.get("publication") or {}).get("status") not in {None, "dry_run"}:
            delivery_eligible += len(product)
    return {"completion": measurement(completed, len(predictions)),
            "failed_analysis": measurement(failed, len(predictions)),
            "abstention": measurement(abstained, len(predictions)),
            "inline_coverage": measurement(anchored, findings),
            "delivery_coverage": measurement(delivered, delivery_eligible)}


def compare_regressions(baseline: dict[str, dict], candidate: dict[str, dict], *,
                        max_latency_multiplier: float = 1.25) -> dict:
    """Compare already adjudicated PR outcomes. Never calls a model judge."""
    regressions = []
    if baseline.keys() != candidate.keys():
        regressions.append({"reason": "case_membership_changed"})
    for case in baseline.keys() & candidate.keys():
        old, new = baseline[case], candidate[case]
        # Matched IDs must come from confirmation/adjudication, not text similarity.
        lost = set(old.get("confirmed_issue_ids", [])) - set(new.get("confirmed_issue_ids", []))
        if lost:
            regressions.append({"case": case, "reason": "confirmed_issue_lost", "issues": sorted(lost)})
        if new.get("known_buggy") and new.get("decision") == "MERGE":
            regressions.append({"case": case, "reason": "merge_on_known_bug"})
        if new.get("fp", 0) > old.get("fp", 0):
            regressions.append({"case": case, "reason": "false_positive_increase"})
        if new.get("health") == "failed" and old.get("health") != "failed":
            regressions.append({"case": case, "reason": "analysis_failure"})
        if old.get("latency_seconds", 0) > 0 and new.get("latency_seconds", 0) > old["latency_seconds"] * max_latency_multiplier:
            regressions.append({"case": case, "reason": "latency_regression"})
    return {"passed": not regressions, "regressions": regressions,
            "paired_cases": len(baseline.keys() & candidate.keys())}
