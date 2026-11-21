"""Paired uncertainty estimates over explicitly adjudicated case outcomes.

This consumes adjudications; it never creates labels or matches model text.
Resampling keeps repository/patch clusters together to avoid independent-case claims.
"""
from __future__ import annotations

import argparse
import json
import math
import random
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from core.domain.review_contracts import ContentHash
from core.review.artifacts import write_json_atomic


class ScoredCase(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)
    case_id: str = Field(min_length=1)
    cluster_id: str = Field(min_length=1)
    source_input_id: ContentHash
    tp: int = Field(ge=0, strict=True)
    fp: int = Field(ge=0, strict=True)
    fn: int = Field(ge=0, strict=True)
    clean_control: bool = Field(strict=True)
    status: Literal["completed", "partial", "failed", "cancelled"]
    latency_seconds: float = Field(ge=0)

    @model_validator(mode="after")
    def clean_has_no_reference_defects(self):
        if self.clean_control and self.tp + self.fn:
            raise ValueError("clean controls cannot contain reference defects")
        return self


def _measure(cases: list[ScoredCase], metric: str) -> float | None:
    if metric == "precision":
        numerator, denominator = sum(case.tp for case in cases), sum(case.tp + case.fp for case in cases)
    elif metric == "recall":
        numerator, denominator = sum(case.tp for case in cases), sum(case.tp + case.fn for case in cases)
    elif metric == "fp_per_clean_pr":
        controls = [case for case in cases if case.clean_control]
        numerator, denominator = sum(case.fp for case in controls), len(controls)
    elif metric == "completion_rate":
        numerator, denominator = sum(case.status == "completed" for case in cases), len(cases)
    else:
        raise ValueError(f"unknown metric: {metric}")
    return numerator / denominator if denominator else None


def paired_analysis(baseline: list[ScoredCase], candidate: list[ScoredCase], *,
                    samples: int = 2000, seed: int = 42) -> dict:
    if not 100 <= samples <= 100_000:
        raise ValueError("bootstrap samples must be between 100 and 100000")
    old = {case.case_id: case for case in baseline}
    new = {case.case_id: case for case in candidate}
    if len(old) != len(baseline) or len(new) != len(candidate):
        raise ValueError("duplicate case IDs")
    if not old or old.keys() != new.keys():
        raise ValueError("paired case membership must be identical and nonempty")
    clusters: dict[str, list[str]] = {}
    for case_id, left in old.items():
        right = new[case_id]
        if (left.source_input_id, left.cluster_id, left.clean_control, left.tp + left.fn) != (
            right.source_input_id, right.cluster_id, right.clean_control, right.tp + right.fn
        ):
            raise ValueError(f"paired inputs or reference labels differ for {case_id}")
        clusters.setdefault(left.cluster_id, []).append(case_id)
    names = sorted(clusters)
    rng = random.Random(seed)
    metrics = ("precision", "recall", "fp_per_clean_pr", "completion_rate")
    differences: dict[str, list[float]] = {metric: [] for metric in metrics}
    for _ in range(samples):
        ids = [case_id for cluster in rng.choices(names, k=len(names)) for case_id in clusters[cluster]]
        left, right = [old[case_id] for case_id in ids], [new[case_id] for case_id in ids]
        for metric in metrics:
            a, b = _measure(left, metric), _measure(right, metric)
            if a is not None and b is not None:
                differences[metric].append(b - a)
    report = {}
    for metric in metrics:
        a, b = _measure(baseline, metric), _measure(candidate, metric)
        values = sorted(differences[metric])
        # A percentile interval is not credible with fewer than two clusters.
        interval = [values[math.floor((len(values) - 1) * q)] for q in (0.025, 0.975)] if values and len(names) > 1 else None
        report[metric] = {"baseline": a, "candidate": b,
                          "delta": b - a if a is not None and b is not None else None,
                          "delta_95_percentile_interval": interval,
                          "valid_bootstrap_samples": len(values)}
    return {"paired_cases": len(old), "independent_clusters": len(names), "bootstrap_samples": samples,
            "seed": seed, "metrics": report,
            "limitations": ["Labels and clean-control status are supplied adjudications, not independently verified by this tool.",
                            "Small cluster counts and undefined bootstrap replicates limit interpretation.",
                            "This report alone does not establish held-out or release eligibility."]}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("baseline", type=Path)
    parser.add_argument("candidate", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--samples", type=int, default=2000)
    args = parser.parse_args()
    def load(path: Path) -> list[ScoredCase]:
        return [ScoredCase.model_validate(item) for item in json.loads(path.read_text())]
    report = paired_analysis(load(args.baseline), load(args.candidate), samples=args.samples)
    write_json_atomic(args.output, report)
    print(f"Analyzed {report['paired_cases']} paired cases in {report['independent_clusters']} clusters")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
