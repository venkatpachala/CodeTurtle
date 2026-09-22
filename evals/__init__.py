"""evals/__init__.py — CodeTurtle Evaluation Framework v1.

Measures all layers of the review pipeline:
  E0  Repository / Graphify knowledge
  E1  Retrieval quality
  E2  Evidence quality
  E3  Hypothesis generation
  E4  Finding quality (Precision / Recall / F1)
  E5  Grounding / evidence citations
  E6  Verification quality
  E7  Final decision quality
  E8  System performance (latency / cost / reliability)
"""

from evals.review.findings import (
    FindingMatcher,
    match_findings_to_golden,
    compute_finding_metrics,
    FindingMetrics,
)
from evals.review.decision import DecisionMetrics, compute_decision_metrics
from evals.system.latency import LatencyStats, compute_latency_stats
from evals.reporting.console import print_report
from evals.reporting.json_report import build_json_report

__all__ = [
    "FindingMatcher",
    "match_findings_to_golden",
    "compute_finding_metrics",
    "FindingMetrics",
    "DecisionMetrics",
    "compute_decision_metrics",
    "LatencyStats",
    "compute_latency_stats",
    "print_report",
    "build_json_report",
]
