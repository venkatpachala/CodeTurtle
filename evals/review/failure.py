"""evals/review/failure.py — Per-PR failure attribution and taxonomy.

For every missed golden issue, classifies WHY it was missed:
  KNOWLEDGE_MISS          - Repository not indexed / graphify failure
  RETRIEVAL_MISS          - Changed file not packed into any bundle
  COVERAGE_MISS           - File packed but LLM didn't see it (bundle overflow)
  CANDIDATE_MISS          - LLM saw context but generated no candidate
  PROOF_MISS              - Candidate generated but incomplete proof fields
  REFLECTOR_REJECTION     - Reflector gate dropped it (not in diff, no line, etc.)
  VERIFIER_REJECTION      - Verifier loop disproved / dropped it
  MATCH_MISS              - Prediction existed but didn't match golden (body mismatch)
  COVERAGE_GAP            - PR file not in any packed bundle at all
  AGENT_FAILURE           - model output/tool/runtime was invalid; not a recall miss
  HYPOTHESIS_MISS         - discovery completed but generated no investigation lead
  EVIDENCE_MISS           - hypotheses existed but retrieval produced no evidence
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


# Failure taxonomy
KNOWLEDGE_MISS = "KNOWLEDGE_MISS"
RETRIEVAL_MISS = "RETRIEVAL_MISS"
COVERAGE_MISS = "COVERAGE_MISS"
CANDIDATE_MISS = "CANDIDATE_MISS"
PROOF_MISS = "PROOF_MISS"
REFLECTOR_REJECTION = "REFLECTOR_REJECTION"
VERIFIER_REJECTION = "VERIFIER_REJECTION"
MATCH_MISS = "MATCH_MISS"
COVERAGE_GAP = "COVERAGE_GAP"
AGENT_FAILURE = "AGENT_FAILURE"
HYPOTHESIS_MISS = "HYPOTHESIS_MISS"
EVIDENCE_MISS = "EVIDENCE_MISS"


@dataclass
class GoldenFailure:
    """One missed golden issue with attributed failure reason."""
    golden_id: str
    golden_comment: str
    golden_category: str
    golden_severity: str
    pr_url: str
    failure_type: str           # see taxonomy above
    detail: str = ""            # human-readable explanation


@dataclass
class FailureReport:
    """Full failure report for all evaluated PRs."""
    total_golden: int = 0
    total_tp: int = 0
    total_missed: int = 0

    failures: List[GoldenFailure] = field(default_factory=list)

    # Failure type distribution
    failure_distribution: Dict[str, int] = field(default_factory=dict)

    # Failure type percentages
    failure_pct: Dict[str, float] = field(default_factory=dict)

    # Failures by category
    category_failures: Dict[str, List[str]] = field(default_factory=dict)

    def add_failure(self, f: GoldenFailure) -> None:
        self.failures.append(f)
        self.failure_distribution[f.failure_type] = self.failure_distribution.get(f.failure_type, 0) + 1
        cats = self.category_failures.setdefault(f.golden_category, [])
        cats.append(f.failure_type)

    def compute_percentages(self) -> None:
        total = sum(self.failure_distribution.values())
        for k, v in self.failure_distribution.items():
            self.failure_pct[k] = round(100 * v / total, 1) if total > 0 else 0.0

    def top_failure_types(self, n: int = 5) -> List[tuple]:
        """Return top N failure types sorted by count."""
        return sorted(self.failure_distribution.items(), key=lambda x: -x[1])[:n]


def attribute_failures(
    pr_url: str,
    unmatched_golden_ids: List[str],
    golden_by_id: Dict[str, Any],  # GoldenIssue by id
    result: Dict[str, Any],         # The raw benchmark result JSON for this PR
) -> List[GoldenFailure]:
    """
    Classify why each unmatched golden issue was missed.

    Uses a deterministic decision tree based on available evidence:
      0. If an agent run is unhealthy → AGENT_FAILURE
      1. If coverage_ratio == 0 or units_total == 0 → RETRIEVAL_MISS
      2. If units_packed < units_total significantly → COVERAGE_GAP
      3. If candidates_generated == 0 → CANDIDATE_MISS
      4. If drop_reasons has incomplete_proof entries → PROOF_MISS
      5. If drop_reasons has reflector entries → REFLECTOR_REJECTION
      6. If drop_reasons has verifier entries → VERIFIER_REJECTION
      7. Otherwise → MATCH_MISS (pipeline ran but body didn't match)
    """
    failures: List[GoldenFailure] = []

    # Extract telemetry from result
    telemetry = result.get("telemetry") or {}
    units_total = int(result.get("coverage_total") or telemetry.get("change_units_total") or 0)
    units_packed = int(result.get("coverage_packed") or telemetry.get("change_units_packed") or 0)
    cov_val = result.get("coverage_ratio") if result.get("coverage_ratio") is not None else telemetry.get("coverage_ratio")
    if cov_val is not None:
        coverage_ratio = float(cov_val)
    elif units_total > 0:
        coverage_ratio = units_packed / units_total
    else:
        coverage_ratio = 0.0
    candidate_count = int(telemetry.get("candidate_count") or 0)
    drop_reasons = dict(telemetry.get("drop_reasons") or {})
    final_findings = int(telemetry.get("verified_count") or 0)
    review_comments = result.get("review_comments") or []
    agent_runs = list(result.get("agent_runs") or telemetry.get("agent_runs") or [])
    healthy_statuses = {"VALID_CANDIDATES", "VALID_EMPTY", "LEGACY"}
    unhealthy_statuses = sorted({
        str(run.get("status") or "UNKNOWN")
        for run in agent_runs
        if isinstance(run, dict) and str(run.get("status") or "UNKNOWN") not in healthy_statuses
    })
    hypothesis_count = sum(int(run.get("hypothesis_count") or 0) for run in agent_runs if isinstance(run, dict))
    evidence_count = sum(int(run.get("evidence_count") or 0) for run in agent_runs if isinstance(run, dict))

    for gid in unmatched_golden_ids:
        golden = golden_by_id.get(gid)
        if golden is None:
            continue

        # Decision tree
        if unhealthy_statuses:
            failure_type = AGENT_FAILURE
            detail = "Agent run was unhealthy: " + ", ".join(unhealthy_statuses)
        elif units_total == 0:
            failure_type = RETRIEVAL_MISS
            detail = "No change units extracted — Graphify may have failed or timed out"
        elif agent_runs and hypothesis_count == 0:
            failure_type = HYPOTHESIS_MISS
            detail = "Discovery completed but generated no hypotheses"
        elif hypothesis_count > 0 and evidence_count == 0:
            failure_type = EVIDENCE_MISS
            detail = f"Generated {hypothesis_count} hypothesis(es) but retrieved no evidence"
        elif hypothesis_count > 0 and candidate_count == 0:
            failure_type = PROOF_MISS
            detail = (
                f"Generated {hypothesis_count} hypothesis(es) and {evidence_count} evidence item(s), "
                "but constructed no proof-complete candidate"
            )
        elif candidate_count == 0 and coverage_ratio >= 0.1:
            failure_type = CANDIDATE_MISS
            detail = "LLM generated zero candidates across all bundles — model may have refused or context was insufficient"
        elif candidate_count == 0 and coverage_ratio < 0.1:
            failure_type = COVERAGE_GAP
            detail = f"Very low coverage ratio ({coverage_ratio:.1%}) AND zero candidates — most changed files were not packed"
        elif drop_reasons.get("incomplete_proof", 0) > 0:
            failure_type = PROOF_MISS
            detail = f"Candidates generated but {drop_reasons['incomplete_proof']} dropped for incomplete proof fields (claim/existing_code/invariant/violating_condition all required)"
        elif drop_reasons.get("note", 0) > 0 and candidate_count > 0:
            failure_type = REFLECTOR_REJECTION
            detail = f"Candidate classified as 'note' not 'defect' ({drop_reasons.get('note',0)} dropped)"
        elif any(k in drop_reasons for k in ("snippet_not_in_hunk", "not_in_pr", "no_line", "hedge")):
            failure_type = REFLECTOR_REJECTION
            detail = f"Reflector gate dropped candidates: {drop_reasons}"
        elif drop_reasons.get("verifier_drop", 0) > 0:
            failure_type = VERIFIER_REJECTION
            detail = f"Verifier disproved or dropped {drop_reasons['verifier_drop']} candidates"
        elif len(review_comments) > 0 and final_findings > 0:
            # Findings were produced but didn't match this golden issue
            failure_type = MATCH_MISS
            detail = f"Pipeline produced {final_findings} finding(s) but none matched this golden issue (semantic mismatch)"
        elif coverage_ratio < 0.5:
            failure_type = COVERAGE_MISS
            detail = f"Coverage ratio {coverage_ratio:.1%} — golden issue file may not have been packed"
        else:
            failure_type = CANDIDATE_MISS
            detail = "Pipeline ran but generated no matching candidate for this issue"

        comment_text = ""
        if hasattr(golden, "comment"):
            comment_text = golden.comment
        elif isinstance(golden, dict):
            comment_text = golden.get("comment", "")

        failures.append(GoldenFailure(
            golden_id=gid,
            golden_comment=comment_text[:150],
            golden_category=getattr(golden, "category", "") or (golden.get("category", "") if isinstance(golden, dict) else ""),
            golden_severity=getattr(golden, "severity", "") or (golden.get("severity", "") if isinstance(golden, dict) else ""),
            pr_url=pr_url,
            failure_type=failure_type,
            detail=detail,
        ))

    return failures
