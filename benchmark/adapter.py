"""benchmark/adapter.py - Adapter for integrating CodeTurtle with Code Review Benchmark."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from benchmark.models import BenchmarkFinding, BenchmarkReview


def review_state_to_benchmark_review(
    state: Dict[str, Any],
    elapsed: float = 0.0,
    model: str = "qwen2.5:7b",
) -> BenchmarkReview:
    """Convert CodeTurtle's final_state dictionary into a BenchmarkReview instance."""
    cov = state.get("review_coverage") or {}
    kept = [
        f
        for f in (state.get("validated_findings") or state.get("findings") or [])
        if isinstance(f, dict) and str(f.get("verify_status") or "").lower() == "verified"
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
    """
    Inject or update a codeturtle review directly in benchmark_data.json.

    This enables downstream benchmark scripts (step2_extract_comments,
    step2_5_dedup, step3_judge_comments) to run directly on codeturtle.
    """
    bm_path = Path(benchmark_data_path).resolve()
    if not bm_path.is_file():
        raise FileNotFoundError(f"benchmark_data.json not found at {bm_path}")

    with open(bm_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    if isinstance(review, Path) or (isinstance(review, str) and str(review).endswith(".json")):
        with open(review, "r", encoding="utf-8") as f:
            raw = json.load(f)
        bm_review = (
            BenchmarkReview(**raw).to_benchmark_data_review()
            if "review_comments" in raw and not any("created_at" in c for c in raw["review_comments"])
            else raw
        )
        pr_url = raw.get("pr_url") or ""
    elif isinstance(review, BenchmarkReview):
        bm_review = review.to_benchmark_data_review()
        pr_url = review.pr_url
    elif isinstance(review, dict):
        if "to_benchmark_data_review" in review:
            bm_review = review.to_benchmark_data_review()
        else:
            bm_review = review
        pr_url = review.get("pr_url") or ""
    else:
        raise TypeError(f"Unsupported review type: {type(review)}")

    # Match PR in benchmark_data.json (canonical key is PR URL or entry['original_url'])
    matched_key = None
    clean_url = pr_url.rstrip("/").lower()
    for key, entry in data.items():
        if key.rstrip("/").lower() == clean_url:
            matched_key = key
            break
        if str(entry.get("original_url") or "").rstrip("/").lower() == clean_url:
            matched_key = key
            break

    if not matched_key:
        return False

    entry = data[matched_key]
    reviews = entry.setdefault("reviews", [])

    # Replace existing codeturtle review if present, else append
    existing_idx = None
    for idx, r in enumerate(reviews):
        if str(r.get("tool") or "").lower() == "codeturtle":
            existing_idx = idx
            break

    if existing_idx is not None:
        reviews[existing_idx] = bm_review
    else:
        reviews.append(bm_review)

    with open(bm_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

    return True
