"""evals/system/latency.py — Stage-level latency statistics.

Computes mean, median, P50, P90, P95, P99 for:
  - Total review latency
  - Per-stage latency (bundle_agent, verify, sandbox, etc.)
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class LatencyStats:
    """Latency statistics for one measurement dimension."""
    count: int = 0
    mean: float = 0.0
    median: float = 0.0
    p50: float = 0.0
    p90: float = 0.0
    p95: float = 0.0
    p99: float = 0.0
    min: float = 0.0
    max: float = 0.0
    total: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "count": self.count,
            "mean_s": round(self.mean, 2),
            "median_s": round(self.median, 2),
            "p90_s": round(self.p90, 2),
            "p95_s": round(self.p95, 2),
            "p99_s": round(self.p99, 2),
            "min_s": round(self.min, 2),
            "max_s": round(self.max, 2),
            "total_s": round(self.total, 2),
        }


def _percentile(values: List[float], p: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    idx = (len(s) - 1) * p / 100.0
    lo, hi = int(idx), min(int(idx) + 1, len(s) - 1)
    frac = idx - lo
    return s[lo] + frac * (s[hi] - s[lo])


def compute_latency_stats(values: List[float]) -> LatencyStats:
    if not values:
        return LatencyStats()
    s = LatencyStats(
        count=len(values),
        mean=sum(values) / len(values),
        median=_percentile(values, 50),
        p50=_percentile(values, 50),
        p90=_percentile(values, 90),
        p95=_percentile(values, 95),
        p99=_percentile(values, 99),
        min=min(values),
        max=max(values),
        total=sum(values),
    )
    return s


@dataclass
class SystemMetrics:
    """All system performance metrics."""
    # Total latency across all PRs
    total_latency: LatencyStats = field(default_factory=LatencyStats)

    # Per-stage latency (from timing records)
    stage_latency: Dict[str, LatencyStats] = field(default_factory=dict)

    # Pipeline success rate
    total_attempts: int = 0
    total_successes: int = 0
    total_failures: int = 0
    success_rate: float = 0.0

    # Coverage metrics
    mean_coverage_ratio: float = 0.0
    median_coverage_ratio: float = 0.0


def compute_system_metrics(
    result_files: List[Dict[str, Any]],
) -> SystemMetrics:
    """Compute system-level performance metrics from result files."""
    m = SystemMetrics()
    m.total_attempts = len(result_files)

    latencies: List[float] = []
    coverages: List[float] = []
    stage_latencies: Dict[str, List[float]] = {}

    for r in result_files:
        lat = r.get("latency_seconds")
        if lat is not None:
            try:
                latencies.append(float(lat))
                m.total_successes += 1
            except (ValueError, TypeError):
                m.total_failures += 1
        else:
            m.total_failures += 1

        cov = r.get("coverage_ratio") or (r.get("telemetry") or {}).get("coverage_ratio")
        if cov is not None:
            try:
                coverages.append(float(cov))
            except (ValueError, TypeError):
                pass

        # Per-stage latencies from telemetry
        telemetry = r.get("telemetry") or {}
        timing = telemetry.get("timing") or {}
        for stage, val in timing.items():
            if stage.endswith("_s") and val:
                try:
                    name = stage[:-2]  # strip "_s"
                    stage_latencies.setdefault(name, []).append(float(val))
                except (ValueError, TypeError):
                    pass

    m.total_latency = compute_latency_stats(latencies)
    m.success_rate = m.total_successes / m.total_attempts if m.total_attempts > 0 else 0.0

    if coverages:
        m.mean_coverage_ratio = sum(coverages) / len(coverages)
        m.median_coverage_ratio = _percentile(coverages, 50)

    for stage, vals in stage_latencies.items():
        m.stage_latency[stage] = compute_latency_stats(vals)

    return m
