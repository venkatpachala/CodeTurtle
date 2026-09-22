"""core/review/timing.py — Stage-level latency tracking for CodeTurtle v4."""

from __future__ import annotations

import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Dict, Generator, Optional


@dataclass
class TimingRecord:
    """Accumulates wall-clock seconds spent in each named review pipeline stage."""
    workspace_s: float = 0.0
    graphify_s: float = 0.0
    pr_facts_s: float = 0.0
    change_units_s: float = 0.0
    bundling_s: float = 0.0
    bundle_agent_s: float = 0.0
    reflect_s: float = 0.0
    verify_s: float = 0.0
    sandbox_s: float = 0.0
    policy_s: float = 0.0
    total_s: float = 0.0
    _extra: Dict[str, float] = field(default_factory=dict, repr=False, compare=False)

    def add(self, stage: str, seconds: float) -> None:
        """Add elapsed seconds to a named stage."""
        attr = f"{stage}_s"
        if hasattr(self, attr):
            setattr(self, attr, getattr(self, attr) + seconds)
        else:
            self._extra[attr] = self._extra.get(attr, 0.0) + seconds

    def to_dict(self) -> Dict[str, float]:
        d: Dict[str, float] = {
            "workspace_s": round(self.workspace_s, 3),
            "graphify_s": round(self.graphify_s, 3),
            "pr_facts_s": round(self.pr_facts_s, 3),
            "change_units_s": round(self.change_units_s, 3),
            "bundling_s": round(self.bundling_s, 3),
            "bundle_agent_s": round(self.bundle_agent_s, 3),
            "reflect_s": round(self.reflect_s, 3),
            "verify_s": round(self.verify_s, 3),
            "sandbox_s": round(self.sandbox_s, 3),
            "policy_s": round(self.policy_s, 3),
            "total_s": round(self.total_s, 3),
        }
        d.update({k: round(v, 3) for k, v in self._extra.items()})
        return d


@contextmanager
def timed(record: TimingRecord, stage: str) -> Generator[None, None, None]:
    """Context manager that times a block and adds its duration to *record*."""
    t0 = time.perf_counter()
    try:
        yield
    finally:
        record.add(stage, time.perf_counter() - t0)
