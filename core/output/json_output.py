"""core/output/json_output.py — Prediction JSON schema for benchmark runs.

Produces the per-PR prediction JSON that is written to:
  benchmark/runs/<run_id>/predictions/pr_NNN.json

This is the canonical benchmark artifact — never mutate benchmark_data.json.
"""

from __future__ import annotations

import platform
import subprocess
import sys
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from core.review.finding import ReviewFinding
    from core.review.trace import PipelineTrace
    from core.review.timing import TimingRecord


def build_prediction_json(
    *,
    repo: str,
    number: int,
    pr_url: str,
    head_sha: str = "",
    model: str = "qwen2.5:7b",
    provider: str = "ollama",
    decision: str = "MERGE",
    policy_reason: str = "no_findings",
    findings: "List[ReviewFinding]",
    pipeline_trace: "Optional[PipelineTrace]" = None,
    timing: "Optional[TimingRecord]" = None,
    coverage: Optional[Dict[str, Any]] = None,
    run_id: str = "",
    codeturtle_commit: str = "",
) -> Dict[str, Any]:
    """Build the complete prediction JSON for one PR.

    Returns a dict ready for JSON serialisation.
    """
    cov = coverage or {}
    total = int(cov.get("units_total") or 0)
    packed = int(cov.get("units_packed") or 0)
    coverage_ratio = round(packed / total, 4) if total > 0 else 0.0

    trace_summary = pipeline_trace.summary() if pipeline_trace else {}
    candidate_count = trace_summary.get("total_candidates", 0)
    final_findings = trace_summary.get("final_findings", 0)
    dropped_count = candidate_count - final_findings

    timing_dict = timing.to_dict() if timing else {}
    latency = timing_dict.get("total_s") or 0.0

    return {
        "schema_version": "1.0",
        "run_id": run_id,
        "tool": "codeturtle",

        "pr": {
            "url": pr_url,
            "repo": repo,
            "number": number,
            "head_sha": head_sha,
        },

        "model": {
            "provider": provider,
            "name": model,
        },

        "review": {
            "decision": decision,
            "policy_reason": policy_reason,
            "findings": [f.to_dict() for f in findings],
        },

        "telemetry": {
            "latency_seconds": round(latency, 2),
            "change_units_total": total,
            "change_units_packed": packed,
            "coverage_ratio": coverage_ratio,
            "candidate_count": candidate_count,
            "verified_count": final_findings,
            "dropped_count": dropped_count,
            "drop_reasons": trace_summary.get("drop_reasons", {}),
            "timing": timing_dict,
        },

        "pipeline_trace": pipeline_trace.to_list() if pipeline_trace else [],

        "reproducibility": {
            "codeturtle_commit": codeturtle_commit or _git_sha(),
            "model": model,
            "python": sys.version.split()[0],
            "platform": platform.system(),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        },
    }


def benchmark_comments_from_findings(findings: "List[ReviewFinding]") -> List[Dict[str, Any]]:
    """Extract the benchmark-compatible comment list from findings.

    Used by CLI --json-output and the old benchmark adapter.
    Format: [{"path": ..., "line": ..., "body": ...}]
    """
    comments = []
    for f in findings:
        if not f.file:
            continue
        comments.append(f.to_benchmark_comment())
    return comments


def _git_sha() -> str:
    """Return the current git HEAD short SHA, or empty string on failure."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        return result.stdout.strip() if result.returncode == 0 else ""
    except Exception:
        return ""
