"""evals/reporting/json_report.py — JSON evaluation report builder."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, TYPE_CHECKING

if TYPE_CHECKING:
    from evals.review.findings import FindingMetrics
    from evals.review.decision import DecisionMetrics
    from evals.review.survival import SurvivalFunnel
    from evals.review.failure import FailureReport
    from evals.system.latency import SystemMetrics


def build_json_report(
    findings,
    decision,
    survival,
    failure_report,
    system,
    *,
    model: str = "",
    dataset_path: str = "",
    run_id: str = "",
) -> Dict[str, Any]:
    """Build a structured JSON evaluation report."""

    pr_results_list = []
    for r in getattr(findings, "pr_results", []):
        pr_results_list.append({
            "pr_url": r.pr_url,
            "tp": r.tp,
            "fp": r.fp,
            "fn": r.fn,
            "golden_count": r.golden_count,
            "predicted_count": r.predicted_count,
            "precision": round(r.precision, 4),
            "recall": round(r.recall, 4),
            "f1": round(r.f1, 4),
            "severity_mae": round(r.severity_mae, 2) if r.severity_mae is not None else None,
        })

    return {
        "schema_version": "1.0",
        "run_id": run_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "model": model,
        "dataset_path": dataset_path,

        "dataset": {
            "prs_evaluated": findings.prs_evaluated,
            "prs_with_predictions": findings.prs_with_predictions,
            "total_golden": findings.total_golden,
            "total_predicted": findings.total_predicted,
        },

        "finding_quality": {
            "precision": round(findings.precision, 4),
            "recall": round(findings.recall, 4),
            "f1": round(findings.f1, 4),
            "precision_ci_95": [round(findings.precision_ci[0], 4), round(findings.precision_ci[1], 4)],
            "recall_ci_95": [round(findings.recall_ci[0], 4), round(findings.recall_ci[1], 4)],
            "f1_ci_95": [round(findings.f1_ci[0], 4), round(findings.f1_ci[1], 4)],
            "tp": findings.total_tp,
            "fp": findings.total_fp,
            "fn": findings.total_fn,
            "fp_per_pr": round(findings.fp_per_pr, 3),
            "pr_detection_rate": round(findings.pr_detection_rate, 4),
            "severity_mae": round(findings.severity_mae, 3) if findings.severity_mae is not None else None,
            "by_category": {
                cat: {k: round(v, 4) if isinstance(v, float) else v for k, v in m.items()}
                for cat, m in findings.category_metrics.items()
            },
        },

        "decision_quality": {
            "prs_evaluated": decision.prs_evaluated,
            "accuracy": round(decision.accuracy, 4),
            "macro_f1": round(decision.macro_f1, 4),
            "over_blocking_rate": round(decision.over_blocking_rate, 4),
            "under_blocking_rate": round(decision.under_blocking_rate, 4),
            "per_class": {
                cls: {k: round(v, 4) if isinstance(v, float) else v for k, v in m.items()}
                for cls, m in decision.per_class.items()
            },
        },

        "pipeline_survival": {
            "total_golden": survival.total_golden,
            "candidates_generated": survival.candidates_generated,
            "candidates_per_pr": round(survival.candidates_per_pr, 2),
            "hypotheses_generated": survival.hypotheses_generated,
            "hypotheses_per_pr": round(survival.hypotheses_per_pr, 2),
            "evidence_items_retrieved": survival.evidence_items_retrieved,
            "units_total": survival.units_total,
            "units_packed": survival.units_packed,
            "units_coverage": round(survival.units_coverage, 4),
            "dropped_classify": survival.dropped_classify,
            "dropped_incomplete_proof": survival.dropped_incomplete_proof,
            "dropped_reflector": survival.dropped_reflector,
            "dropped_no_line": survival.dropped_no_line,
            "survived_reflector": survival.survived_reflector,
            "dropped_verifier": survival.dropped_verifier,
            "final_findings": survival.final_findings,
            "final_findings_per_pr": round(survival.final_findings_per_pr, 2),
            "drop_reasons": survival.drop_reasons,
            "agent_runs": survival.agent_runs,
            "unhealthy_agent_runs": survival.unhealthy_agent_runs,
            "agent_statuses": survival.agent_statuses,
        },

        "failure_attribution": {
            "total_missed": failure_report.total_missed,
            "distribution": failure_report.failure_distribution,
            "percentages": failure_report.failure_pct,
            "top_failures": [
                {
                    "pr_url": f.pr_url,
                    "golden_id": f.golden_id,
                    "category": f.golden_category,
                    "severity": f.golden_severity,
                    "failure_type": f.failure_type,
                    "detail": f.detail,
                    "comment": f.golden_comment[:200],
                }
                for f in failure_report.failures[:20]
            ],
        },

        "system_performance": {
            "total_attempts": system.total_attempts,
            "total_successes": system.total_successes,
            "total_failures": system.total_failures,
            "success_rate": round(system.success_rate, 4),
            "latency": system.total_latency.to_dict(),
            "mean_coverage_ratio": round(system.mean_coverage_ratio, 4),
            "median_coverage_ratio": round(system.median_coverage_ratio, 4),
            "stage_latency": {
                stage: sl.to_dict()
                for stage, sl in system.stage_latency.items()
            },
        },

        "per_pr_results": pr_results_list,
    }
