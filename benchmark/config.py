"""benchmark/config.py — BenchmarkConfig dataclass and YAML loader.

Usage:
    cfg = load_benchmark_config("benchmark/configs/baseline.yaml")
    print(cfg.model, cfg.judge_model)
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional


@dataclass
class BenchmarkConfig:
    # ── Model ────────────────────────────────────────────────────────────────
    model: str = "qwen2.5:7b"
    provider: str = "ollama"
    base_url: str = "http://localhost:11434/v1"

    # ── Review runtime ───────────────────────────────────────────────────────
    runtime: str = "v4"
    bundle_max: int = 4
    agent_max_steps: int = 4

    # ── Verification ─────────────────────────────────────────────────────────
    verification_enabled: bool = True

    # ── Execution (sandbox) ──────────────────────────────────────────────────
    execution_enabled: bool = False
    execution_install: bool = False

    # ── Benchmark evaluation ─────────────────────────────────────────────────
    judge_model: str = "qwen2.5:7b"
    judge_base_url: str = "http://localhost:11434/v1"
    graphify_timeout: int = 3600
    review_timeout: int = 900

    # ── Run selection ────────────────────────────────────────────────────────
    start: int = 0
    limit: Optional[int] = None

    # ── Dataset path ─────────────────────────────────────────────────────────
    dataset_path: str = ""

    # ── Output ───────────────────────────────────────────────────────────────
    runs_dir: str = "benchmark/runs"

    # ── Product release gate ────────────────────────────────────────────────
    min_gate_prs: int = 10
    min_precision: float = 0.80
    min_blocking_recall: float = 0.60
    max_fp_per_pr: float = 0.30
    min_agent_success_rate: float = 0.95
    max_p95_latency_seconds: float = 300.0
    min_decision_accuracy: float = 0.70
    max_over_blocking_rate: float = 0.10

    # ── Raw config dict for forward compatibility ────────────────────────────
    _raw: Dict[str, Any] = field(default_factory=dict, repr=False)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "model": self.model,
            "provider": self.provider,
            "base_url": self.base_url,
            "runtime": self.runtime,
            "bundle_max": self.bundle_max,
            "agent_max_steps": self.agent_max_steps,
            "verification_enabled": self.verification_enabled,
            "execution_enabled": self.execution_enabled,
            "execution_install": self.execution_install,
            "judge_model": self.judge_model,
            "judge_base_url": self.judge_base_url,
            "graphify_timeout": self.graphify_timeout,
            "review_timeout": self.review_timeout,
            "start": self.start,
            "limit": self.limit,
            "dataset_path": self.dataset_path,
            "runs_dir": self.runs_dir,
            "release_gate": self.release_thresholds(),
        }

    def release_thresholds(self) -> Dict[str, Any]:
        return {
            "min_prs": self.min_gate_prs,
            "min_precision": self.min_precision,
            "min_blocking_recall": self.min_blocking_recall,
            "max_fp_per_pr": self.max_fp_per_pr,
            "min_agent_success_rate": self.min_agent_success_rate,
            "max_p95_latency_seconds": self.max_p95_latency_seconds,
            "min_decision_accuracy": self.min_decision_accuracy,
            "max_over_blocking_rate": self.max_over_blocking_rate,
        }


_DEFAULT_YAML = """
run:
  model: qwen2.5:7b
  provider: ollama
  base_url: http://localhost:11434/v1

review:
  runtime: v4
  bundle_max: 4
  agent_max_steps: 4

verification:
  enabled: true

execution:
  enabled: false
  install: false

benchmark:
  judge_model: qwen2.5:7b
  judge_base_url: http://localhost:11434/v1
  graphify_timeout: 3600
  review_timeout: 900

dataset:
  path: ""

output:
  runs_dir: benchmark/runs

release_gate:
  min_prs: 10
  min_precision: 0.80
  min_blocking_recall: 0.60
  max_fp_per_pr: 0.30
  min_agent_success_rate: 0.95
  max_p95_latency_seconds: 300
  min_decision_accuracy: 0.70
  max_over_blocking_rate: 0.10
"""


def load_benchmark_config(path: str = "") -> BenchmarkConfig:
    """Load benchmark config from YAML file, falling back to defaults.

    Args:
        path: Path to a benchmark config YAML file. If empty, uses defaults.

    Returns:
        BenchmarkConfig with all fields populated.
    """
    raw: Dict[str, Any] = {}

    if path:
        cfg_path = Path(path)
        if not cfg_path.is_file():
            raise FileNotFoundError(f"Benchmark config not found: {cfg_path}")
        try:
            import yaml  # type: ignore

            with open(cfg_path, "r", encoding="utf-8") as f:
                raw = yaml.safe_load(f) or {}
        except ImportError:
            # Fall back to simple key=value parsing if PyYAML not available
            raw = _simple_yaml_parse(cfg_path)

    run = dict(raw.get("run") or {})
    review = dict(raw.get("review") or {})
    verification = dict(raw.get("verification") or {})
    execution = dict(raw.get("execution") or {})
    benchmark = dict(raw.get("benchmark") or {})
    dataset = dict(raw.get("dataset") or {})
    output = dict(raw.get("output") or {})
    release_gate = dict(raw.get("release_gate") or {})

    return BenchmarkConfig(
        model=str(run.get("model") or os.environ.get("OLLAMA_MODEL") or "qwen2.5:7b"),
        provider=str(run.get("provider") or "ollama"),
        base_url=str(run.get("base_url") or "http://localhost:11434/v1"),
        runtime=str(review.get("runtime") or "v4"),
        bundle_max=int(review.get("bundle_max") or 4),
        agent_max_steps=int(review.get("agent_max_steps") or 4),
        verification_enabled=bool(verification.get("enabled", True)),
        execution_enabled=bool(execution.get("enabled", False)),
        execution_install=bool(execution.get("install", False)),
        judge_model=str(benchmark.get("judge_model") or "qwen2.5:7b"),
        judge_base_url=str(benchmark.get("judge_base_url") or "http://localhost:11434/v1"),
        graphify_timeout=int(benchmark.get("graphify_timeout") or 3600),
        review_timeout=int(benchmark.get("review_timeout") or 900),
        dataset_path=str(dataset.get("path") or ""),
        runs_dir=str(output.get("runs_dir") or "benchmark/runs"),
        min_gate_prs=int(release_gate.get("min_prs") or 10),
        min_precision=float(release_gate.get("min_precision") or 0.80),
        min_blocking_recall=float(release_gate.get("min_blocking_recall") or 0.60),
        max_fp_per_pr=float(release_gate.get("max_fp_per_pr") or 0.30),
        min_agent_success_rate=float(release_gate.get("min_agent_success_rate") or 0.95),
        max_p95_latency_seconds=float(release_gate.get("max_p95_latency_seconds") or 300.0),
        min_decision_accuracy=float(release_gate.get("min_decision_accuracy") or 0.70),
        max_over_blocking_rate=float(release_gate.get("max_over_blocking_rate") or 0.10),
        _raw=raw,
    )


def _simple_yaml_parse(path: Path) -> Dict[str, Any]:
    """Minimal YAML parser for flat key=value YAML (no nesting)."""
    result: Dict[str, Any] = {}
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if ":" in line:
                key, _, val = line.partition(":")
                result[key.strip()] = val.strip()
    return result
