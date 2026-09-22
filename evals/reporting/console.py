"""evals/reporting/console.py — Rich console evaluation report.

Prints a comprehensive ASCII table report with all metrics.
No mocking — all numbers come from real evaluation.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from evals.review.findings import FindingMetrics
    from evals.review.decision import DecisionMetrics
    from evals.review.survival import SurvivalFunnel
    from evals.review.failure import FailureReport
    from evals.system.latency import SystemMetrics


def _pct(v: float) -> str:
    return f"{v * 100:.1f}%"


def _fmt(v: Optional[float], decimals: int = 1) -> str:
    if v is None:
        return "N/A"
    return f"{v:.{decimals}f}"


def print_report(
    findings,
    decision,
    survival,
    failure_report,
    system,
    *,
    model: str = "",
    dataset_path: str = "",
    run_id: str = "",
) -> str:
    """Print and return the full evaluation report string."""
    lines = []

    def ln(s: str = "") -> None:
        lines.append(s)
        print(s)

    thin = "─" * 68

    ln()
    ln("=" * 68)
    ln("  CodeTurtle Evaluation Report")
    if run_id:
        ln(f"  Run ID  : {run_id}")
    if model:
        ln(f"  Model   : {model}")
    if dataset_path:
        ln(f"  Dataset : {dataset_path}")
    ln("=" * 68)

    # ── Dataset Summary ──────────────────────────────────────────────────────
    ln()
    ln("  DATASET")
    ln(thin)
    ln(f"  {'PRs Evaluated':<35} {findings.prs_evaluated:>8}")
    ln(f"  {'PRs with Predictions':<35} {findings.prs_with_predictions:>8}")
    ln(f"  {'Total Golden Issues':<35} {findings.total_golden:>8}")
    ln(f"  {'Total Predictions':<35} {findings.total_predicted:>8}")

    # ── Finding Quality ──────────────────────────────────────────────────────
    ln()
    ln("  FINDING QUALITY  (E4 — Precision / Recall / F1)")
    ln(thin)
    p_lo, p_hi = findings.precision_ci
    r_lo, r_hi = findings.recall_ci
    f_lo, f_hi = findings.f1_ci
    ln(f"  {'Metric':<35} {'Value':>12}  95% CI")
    ln(f"  {'-'*35} {'-'*12}  {'─'*20}")
    ln(f"  {'Precision':<35} {_pct(findings.precision):>12}  [{_pct(p_lo)} – {_pct(p_hi)}]")
    ln(f"  {'Recall':<35} {_pct(findings.recall):>12}  [{_pct(r_lo)} – {_pct(r_hi)}]")
    ln(f"  {'F1 Score':<35} {_pct(findings.f1):>12}  [{_pct(f_lo)} – {_pct(f_hi)}]")
    ln(f"  {'True Positives (TP)':<35} {findings.total_tp:>12}")
    ln(f"  {'False Positives (FP)':<35} {findings.total_fp:>12}")
    ln(f"  {'False Negatives / Missed (FN)':<35} {findings.total_fn:>12}")
    ln(f"  {'False Positives / PR':<35} {_fmt(findings.fp_per_pr, 2):>12}")
    ln(f"  {'PR Detection Rate':<35} {_pct(findings.pr_detection_rate):>12}  PRs with ≥1 TP")
    if findings.severity_mae is not None:
        ln(f"  {'Severity MAE (ordinal 0–4)':<35} {_fmt(findings.severity_mae, 2):>12}")

    # ── Per-Category Breakdown ──────────────────────────────────────────────
    if findings.category_metrics:
        ln()
        ln("  FINDING QUALITY BY CATEGORY")
        ln(thin)
        ln(f"  {'Category':<20} {'Prec':>8} {'Rec':>8} {'F1':>8} {'TP':>5} {'FP':>5} {'FN':>5}")
        ln(f"  {'-'*20} {'-'*8} {'-'*8} {'-'*8} {'-'*5} {'-'*5} {'-'*5}")
        for cat, metrics in sorted(findings.category_metrics.items()):
            ln(
                f"  {cat:<20} "
                f"{_pct(metrics['precision']):>8} "
                f"{_pct(metrics['recall']):>8} "
                f"{_pct(metrics['f1']):>8} "
                f"{int(metrics['tp']):>5} "
                f"{int(metrics['fp']):>5} "
                f"{int(metrics['fn']):>5}"
            )

    # ── Decision Quality ─────────────────────────────────────────────────────
    ln()
    ln("  DECISION QUALITY  (E6)")
    ln(thin)
    ln(f"  {'PRs with Known Decision':<35} {decision.prs_evaluated:>8}")
    ln(f"  {'Decision Accuracy':<35} {_pct(decision.accuracy):>12}")
    ln(f"  {'Macro F1':<35} {_pct(decision.macro_f1):>12}")
    ln(f"  {'Over-blocking (MERGE→REQUEST)':<35} {_pct(decision.over_blocking_rate):>12}")
    ln(f"  {'Under-blocking (REQUEST→MERGE)':<35} {_pct(decision.under_blocking_rate):>12}")

    if decision.per_class:
        ln()
        from evals.review.decision import DECISION_CLASSES
        ln(f"  {'Class':<25} {'Prec':>8} {'Rec':>8} {'F1':>8} {'Supp':>6}")
        ln(f"  {'-'*25} {'-'*8} {'-'*8} {'-'*8} {'-'*6}")
        for cls in DECISION_CLASSES:
            m = decision.per_class.get(cls, {})
            if m and m.get("support", 0) > 0:
                ln(
                    f"  {cls:<25} "
                    f"{_pct(m['precision']):>8} "
                    f"{_pct(m['recall']):>8} "
                    f"{_pct(m['f1']):>8} "
                    f"{int(m['support']):>6}"
                )

        # Confusion matrix
        if decision.prs_evaluated > 0:
            ln()
            ln("  Confusion Matrix  (rows = gold, cols = predicted)")
            header = f"  {'Gold \\ Pred':<20}" + "".join(f"{c[:12]:>13}" for c in DECISION_CLASSES)
            ln(header)
            ln(f"  {'-'*20}" + "-" * 39)
            for gold in DECISION_CLASSES:
                row = f"  {gold:<20}"
                for pred in DECISION_CLASSES:
                    v = decision.confusion.get(gold, {}).get(pred, 0)
                    row += f"{v:>13}"
                ln(row)

    # ── Pipeline Survival Funnel ─────────────────────────────────────────────
    ln()
    ln("  PIPELINE SURVIVAL FUNNEL  (Where is recall lost?)")
    ln(thin)
    ln(f"  {'Stage':<42} {'Count':>8} {'%':>10}")
    ln(f"  {'-'*42} {'-'*8} {'-'*10}")
    for row in survival.funnel_rows():
        stage = row["stage"]
        count = row["count"]
        pct_str = row.get("drop_pct") or row.get("relative") or "-"
        ln(f"  {stage:<42} {count:>8} {pct_str:>10}")
    if survival.agent_runs:
        ln(f"  {'Agent runs / unhealthy':<42} {survival.agent_runs:>4} / {survival.unhealthy_agent_runs:<3}")
        ln(f"  {'Agent statuses':<42} {str(survival.agent_statuses):>8}")

    # ── Failure Attribution ──────────────────────────────────────────────────
    if failure_report.failures:
        ln()
        ln("  FAILURE ATTRIBUTION  (Why were golden issues missed?)")
        ln(thin)
        failure_report.compute_percentages()
        ln(f"  {'Failure Type':<35} {'N':>5}  {'%':>7}")
        ln(f"  {'-'*35} {'-'*5}  {'-'*7}")
        for ftype, count in failure_report.top_failure_types(n=8):
            pct = failure_report.failure_pct.get(ftype, 0.0)
            ln(f"  {ftype:<35} {count:>5}  {pct:>6.1f}%")

        if failure_report.failures:
            ln()
            ln(f"  Sample missed golden issues ({min(5, len(failure_report.failures))} shown):")
            for i, f in enumerate(failure_report.failures[:5], 1):
                ln(f"  [{i}] [{f.golden_category}|{f.golden_severity}]")
                ln(f"      {f.golden_comment[:90]}")
                ln(f"      → {f.failure_type}: {f.detail[:85]}")

    # ── System Performance ────────────────────────────────────────────────────
    tl = system.total_latency
    ln()
    ln("  SYSTEM PERFORMANCE  (E8 — Latency & Reliability)")
    ln(thin)
    ln(f"  {'Pipeline Success Rate':<35} {_pct(system.success_rate):>12}")
    ln(f"  {'Total PRs Attempted':<35} {system.total_attempts:>12}")
    ln(f"  {'Failures / Timeouts':<35} {system.total_failures:>12}")
    if tl.count > 0:
        ln(f"  {'Mean Latency':<35} {_fmt(tl.mean, 1):>11}s")
        ln(f"  {'Median (P50)':<35} {_fmt(tl.median, 1):>11}s")
        ln(f"  {'P90':<35} {_fmt(tl.p90, 1):>11}s")
        ln(f"  {'P95':<35} {_fmt(tl.p95, 1):>11}s")
        ln(f"  {'P99':<35} {_fmt(tl.p99, 1):>11}s")
        ln(f"  {'Min / Max':<35} {_fmt(tl.min,1):>5}s / {_fmt(tl.max,1)}s")
    ln(f"  {'Mean Coverage Ratio':<35} {_pct(system.mean_coverage_ratio):>12}")
    ln(f"  {'Median Coverage Ratio':<35} {_pct(system.median_coverage_ratio):>12}")

    if system.stage_latency:
        ln()
        ln(f"  Per-Stage Latency:")
        ln(f"  {'Stage':<25} {'Mean':>8} {'P50':>8} {'P95':>8} {'N':>5}")
        ln(f"  {'-'*25} {'-'*8} {'-'*8} {'-'*8} {'-'*5}")
        for stage, sl in sorted(system.stage_latency.items()):
            if sl.count > 0:
                ln(f"  {stage:<25} {_fmt(sl.mean,1):>7}s {_fmt(sl.p50,1):>7}s {_fmt(sl.p95,1):>7}s {sl.count:>5}")

    ln()
    ln("=" * 68)

    return "\n".join(lines)
