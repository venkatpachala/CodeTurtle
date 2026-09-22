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

    findings_list = list(getattr(result, "findings", None) or [])
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
        decision=str(getattr(result, "decision", "COMMENT") or "COMMENT"),
        policy_reason=str(getattr(result, "policy_reason", "") or ""),
        latency_seconds=round(elapsed, 2) if elapsed else None,
        coverage_total=total,
        coverage_packed=packed,
        coverage_ratio=ratio_f,
        review_comments=bm_findings,
    )


def review_state_to_benchmark_review(
    state: Dict[str, Any],
    elapsed: float = 0.0,
    model: str = "qwen2.5:7b",
) -> BenchmarkReview:
    """Convert CodeTurtle's final_state dictionary into a BenchmarkReview instance.

    UPDATED: No longer filters by verify_status == 'verified'.
    All findings that survived the pipeline are included.
    The old filter was the root cause of zero review_comments in benchmark output.
    """
    cov = state.get("review_coverage") or {}

    # Prefer ReviewFinding objects attached to result if available
    review_result = state.get("_review_result")
    if review_result is not None and hasattr(review_result, "findings"):
        repo = str(state.get("repo") or "")
        number = int(state.get("number") or 0)
        return review_result_to_benchmark_review(
            review_result,
            repo=repo,
            number=number,
            elapsed=elapsed,
            model=model,
        )

    # Legacy path: build from validated_findings dict list
    all_findings = list(state.get("validated_findings") or state.get("findings") or [])
    # Include all findings (not just verified) — drop only explicitly disproved
    kept = [
        f
        for f in all_findings
        if isinstance(f, dict)
        and str(f.get("verify_status") or "").lower() != "disproved"
    ]

    findings: List[BenchmarkFinding] = []
    for f in kept:
        title = str(f.get("title") or "").strip()
        claim = str(f.get("claim") or "").strip()
        body = f"{title}\n\n{claim}".strip() if claim else title
        line_raw = f.get("line") or f.get("start_line")
        try:
            line = int(line_raw) if line_raw and int(line_raw) > 0 else None
        except (ValueError, TypeError):
            line = None
        if title and str(f.get("file") or ""):
            findings.append(
                BenchmarkFinding(
                    path=str(f.get("file") or ""),
                    line=line,
                    body=body,
                )
            )

    repo = str(state.get("repo") or "")
    number = int(state.get("number") or 0)
    pr_url = f"https://github.com/{repo}/pull/{number}" if repo and number else ""

    ratio = state.get("coverage_ratio")
    try:
        ratio_f = float(ratio) if ratio is not None else None
    except (ValueError, TypeError):
        ratio_f = None

    return BenchmarkReview(
        tool="codeturtle",
        pr_url=pr_url,
        repo_name=repo,
        model=model,
        decision=str(state.get("recommendation") or "COMMENT"),
        policy_reason=str(state.get("policy_reason") or ""),
        latency_seconds=round(elapsed, 2) if elapsed else None,
        coverage_total=int(cov.get("units_total") or 0),
        coverage_packed=int(cov.get("units_packed") or 0),
        coverage_ratio=ratio_f,
        review_comments=findings,
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
