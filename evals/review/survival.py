"""evals/review/survival.py — Pipeline candidate survival analysis.

Traces where golden issues are lost in the pipeline:
  candidate generated? → survived reflector? → survived verifier? → final finding?

Computes the "recall funnel" showing at which stage recall is lost.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class SurvivalFunnel:
    """Survival counts at each pipeline stage."""
    total_golden: int = 0

    # How many PRs were evaluated
    prs_evaluated: int = 0

    # Change unit stage
    units_total: int = 0
    units_packed: int = 0
    units_coverage: float = 0.0

    # Candidate generation stage
    candidates_generated: int = 0
    candidates_per_pr: float = 0.0
    hypotheses_generated: int = 0
    evidence_items_retrieved: int = 0
    hypotheses_per_pr: float = 0.0

    # Reflector stage
    survived_reflector: int = 0
    dropped_classify: int = 0       # kind != defect
    dropped_incomplete_proof: int = 0
    dropped_reflector: int = 0      # reflect_candidate rejected
    dropped_no_line: int = 0

    # Verifier stage
    survived_verifier: int = 0
    dropped_verifier: int = 0

    # Final findings
    final_findings: int = 0
    final_findings_per_pr: float = 0.0

    # Agent execution health.  This prevents zero-candidate output from being
    # misread as a model recall failure when the model/parser/tool failed.
    agent_runs: int = 0
    unhealthy_agent_runs: int = 0
    agent_statuses: Dict[str, int] = field(default_factory=dict)

    # Drop reason breakdown
    drop_reasons: Dict[str, int] = field(default_factory=dict)

    # Estimated recall at each stage (relative to golden)
    # Note: this is a rough estimate - we can't directly map candidates to golden issues
    # without a matcher, but we track quantities for funnel visualization
    def funnel_rows(self) -> List[Dict[str, Any]]:
        """Return rows for the funnel table."""
        rows = []
        def pct(n, total=None):
            t = total or self.total_golden or 1
            return f"{100*n/t:.1f}%" if t > 0 else "N/A"

        rows.append({
            "stage": "Golden Issues",
            "count": self.total_golden,
            "relative": "100.0%",
            "drop_pct": "-",
        })
        rows.append({
            "stage": "PRs Evaluated",
            "count": self.prs_evaluated,
            "relative": "-",
            "drop_pct": "-",
        })
        rows.append({
            "stage": "Change Units Total",
            "count": self.units_total,
            "relative": "-",
            "drop_pct": "-",
        })
        rows.append({
            "stage": "Change Units Packed",
            "count": self.units_packed,
            "relative": f"{100*self.units_coverage:.1f}%" if self.units_coverage else "N/A",
            "drop_pct": "-",
        })
        rows.append({
            "stage": "Hypotheses Generated",
            "count": self.hypotheses_generated,
            "relative": "-",
            "drop_pct": "-",
        })
        rows.append({
            "stage": "Evidence Items Retrieved",
            "count": self.evidence_items_retrieved,
            "relative": "-",
            "drop_pct": "-",
        })
        rows.append({
            "stage": "Candidates Generated",
            "count": self.candidates_generated,
            "relative": "-",
            "drop_pct": "-",
        })
        rows.append({
            "stage": "  ↳ Dropped (not defect)",
            "count": self.dropped_classify,
            "relative": "-",
            "drop_pct": pct(self.dropped_classify, self.candidates_generated),
        })
        rows.append({
            "stage": "  ↳ Dropped (incomplete proof)",
            "count": self.dropped_incomplete_proof,
            "relative": "-",
            "drop_pct": pct(self.dropped_incomplete_proof, self.candidates_generated),
        })
        rows.append({
            "stage": "  ↳ Dropped (reflector gate)",
            "count": self.dropped_reflector,
            "relative": "-",
            "drop_pct": pct(self.dropped_reflector, self.candidates_generated),
        })
        rows.append({
            "stage": "  ↳ Dropped (no line position)",
            "count": self.dropped_no_line,
            "relative": "-",
            "drop_pct": pct(self.dropped_no_line, self.candidates_generated),
        })
        rows.append({
            "stage": "Survived Reflector",
            "count": self.survived_reflector,
            "relative": pct(self.survived_reflector, self.candidates_generated),
            "drop_pct": "-",
        })
        rows.append({
            "stage": "  ↳ Dropped (verifier)",
            "count": self.dropped_verifier,
            "relative": "-",
            "drop_pct": pct(self.dropped_verifier, self.survived_reflector),
        })
        rows.append({
            "stage": "Final Findings",
            "count": self.final_findings,
            "relative": pct(self.final_findings, self.candidates_generated),
            "drop_pct": "-",
        })
        return rows


def aggregate_survival_from_results(
    result_files: List[Dict[str, Any]],
    golden_counts: Dict[str, int],
) -> SurvivalFunnel:
    """
    Build a survival funnel from benchmark result JSONs.

    Args:
        result_files: list of loaded result JSON dicts (one per PR)
        golden_counts: {pr_url: count_of_golden_issues}

    Returns:
        SurvivalFunnel
    """
    funnel = SurvivalFunnel()
    funnel.prs_evaluated = len(result_files)
    funnel.total_golden = sum(golden_counts.values())

    drop_reasons: Dict[str, int] = defaultdict(int)

    for r in result_files:
        for run in list(r.get("agent_runs") or (r.get("telemetry") or {}).get("agent_runs") or []):
            if not isinstance(run, dict):
                continue
            status = str(run.get("status") or "UNKNOWN")
            funnel.agent_runs += 1
            funnel.hypotheses_generated += int(run.get("hypothesis_count") or 0)
            funnel.evidence_items_retrieved += int(run.get("evidence_count") or 0)
            funnel.agent_statuses[status] = funnel.agent_statuses.get(status, 0) + 1
            if status not in {"VALID_CANDIDATES", "VALID_EMPTY", "LEGACY"}:
                funnel.unhealthy_agent_runs += 1
        # Coverage
        funnel.units_total += int(r.get("coverage_total") or r.get("units_total") or 0)
        funnel.units_packed += int(r.get("coverage_packed") or r.get("units_packed") or 0)

        # Pipeline trace (if present in new format)
        trace = r.get("pipeline_trace") or []
        for event in trace:
            if not isinstance(event, dict):
                continue
            stage = event.get("stage", "")
            status = event.get("status", "")
            reason = event.get("drop_reason") or ""
            if status == "dropped":
                drop_reasons[reason] += 1
                if reason == "note":
                    funnel.dropped_classify += 1
                elif reason == "incomplete_proof":
                    funnel.dropped_incomplete_proof += 1
                elif stage in ("reflector",):
                    funnel.dropped_reflector += 1
                elif reason == "no_line":
                    funnel.dropped_no_line += 1
                elif stage == "verifier":
                    funnel.dropped_verifier += 1

        # Telemetry (new format)
        telemetry = r.get("telemetry") or {}
        if telemetry:
            funnel.candidates_generated += int(telemetry.get("candidate_count") or 0)
            funnel.final_findings += int(telemetry.get("verified_count") or 0)
            dropped = telemetry.get("drop_reasons") or {}
            for k, v in dropped.items():
                drop_reasons[k] += v
        else:
            # Legacy format: infer from review_comments
            comments = r.get("review_comments") or []
            funnel.final_findings += len(comments)

    # Derived
    if funnel.units_total > 0:
        funnel.units_coverage = funnel.units_packed / funnel.units_total
    funnel.survived_reflector = max(0, funnel.candidates_generated - funnel.dropped_classify - funnel.dropped_incomplete_proof - funnel.dropped_reflector - funnel.dropped_no_line)
    funnel.candidates_per_pr = funnel.candidates_generated / funnel.prs_evaluated if funnel.prs_evaluated > 0 else 0.0
    funnel.hypotheses_per_pr = funnel.hypotheses_generated / funnel.prs_evaluated if funnel.prs_evaluated > 0 else 0.0
    funnel.final_findings_per_pr = funnel.final_findings / funnel.prs_evaluated if funnel.prs_evaluated > 0 else 0.0
    funnel.drop_reasons = dict(drop_reasons)

    return funnel
