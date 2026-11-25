"""benchmark/adapter.py - Adapter for integrating CodeTurtle with Code Review Benchmark."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Union

from benchmark.models import BenchmarkFinding, BenchmarkReview


def review_result_to_benchmark_review(
    result: Any,
    *,
    repo: str = "",
    number: int = 0,
    elapsed: float = 0.0,
    model: str = "qwen2.5:7b",
) -> BenchmarkReview:
    """Convert a ReviewResult (from core.runtime.models) into a BenchmarkReview.

    This is the canonical new path. Uses result.findings (List[ReviewFinding])
    directly — no secondary filtering by verify_status.
    """
    cov = dict(getattr(result, "coverage", None) or {})
    pr_url = f"https://github.com/{repo}/pull/{number}" if repo and number else ""
    total = int(cov.get("units_total") or 0)
    packed = int(cov.get("units_packed") or 0)
    ratio_f = round(packed / total, 4) if total > 0 else None

    findings_list = list(result.product_findings)
    bm_findings: List[BenchmarkFinding] = []
    for rf in findings_list:
        comment = rf.to_benchmark_comment()
        path = str(comment.get("path") or "")
        line = comment.get("line")
        body = str(comment.get("body") or "")
        if path and body:
            bm_findings.append(BenchmarkFinding(path=path, line=line, body=body))

    return BenchmarkReview(
        tool="codeturtle",
        pr_url=pr_url,
        repo_name=repo,
        model=model,
        decision=str(result.decision or "NO_VERDICT"),
        policy_reason=str(getattr(result, "policy_reason", "") or ""),
        latency_seconds=round(elapsed, 2) if elapsed else None,
        coverage_total=total,
        coverage_packed=packed,
        coverage_ratio=ratio_f,
        review_comments=bm_findings,
    )


def inject_review_into_benchmark_data(
    benchmark_data_path: Union[str, Path],
    review: Union[BenchmarkReview, Dict[str, Any], Path],
) -> bool:
    """Retired compatibility shim.

    Benchmark datasets are immutable input.  Write predictions under
    ``benchmark/runs/<run-id>/predictions`` instead.
    """
    raise RuntimeError(
        "Mutating benchmark_data.json is retired; use benchmark/run.py outputs."
    )
