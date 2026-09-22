"""Deterministic product-quality release gates for benchmark runs."""

from __future__ import annotations

from typing import Any


def evaluate_release_gate(metrics: dict[str, Any], thresholds: dict[str, Any]) -> dict[str, Any]:
    actionable = metrics.get("actionable") or {}
    decision = metrics.get("decision") or {}
    observed = {
        "prs": int(metrics.get("prs") or 0),
        "actionable_precision": float(actionable.get("precision") or 0.0),
        "blocking_recall": float(actionable.get("blocking_recall") or 0.0),
        "fp_per_pr": float(metrics.get("fp_per_pr") or 0.0),
        "agent_run_success_rate": float(metrics.get("agent_run_success_rate") or 0.0),
        "p95_latency_seconds": float((metrics.get("latency_seconds") or {}).get("p95") or 0.0),
        "decision_accuracy": float(decision.get("accuracy") or 0.0),
        "over_blocking_rate": float(decision.get("over_blocking_rate") or 0.0),
    }
    checks = {
        "minimum_sample": observed["prs"] >= int(thresholds.get("min_prs", 10)),
        "actionable_precision": observed["actionable_precision"] >= float(thresholds.get("min_precision", 0.8)),
        "blocking_recall": observed["blocking_recall"] >= float(thresholds.get("min_blocking_recall", 0.6)),
        "fp_per_pr": observed["fp_per_pr"] <= float(thresholds.get("max_fp_per_pr", 0.3)),
        "agent_reliability": observed["agent_run_success_rate"] >= float(thresholds.get("min_agent_success_rate", 0.95)),
        "latency": observed["p95_latency_seconds"] <= float(thresholds.get("max_p95_latency_seconds", 300.0)),
        "decision_accuracy": observed["decision_accuracy"] >= float(thresholds.get("min_decision_accuracy", 0.7)),
        "over_blocking": observed["over_blocking_rate"] <= float(thresholds.get("max_over_blocking_rate", 0.1)),
    }
    return {
        "passed": all(checks.values()),
        "checks": checks,
        "observed": observed,
        "thresholds": dict(thresholds),
    }
