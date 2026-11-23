"""Shared bounded model work. Wall time is checked between calls."""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Literal


class BudgetExceeded(RuntimeError):
    pass


Lane = Literal["discovery", "investigation", "verification", "general"]


@dataclass
class ReviewBudget:
    max_model_calls: int = 12
    max_prompt_chars: int = 120000
    max_wall_seconds: float = 300.0
    calls: int = 0
    prompt_chars: int = 0
    started: float = field(default_factory=time.monotonic)
    calls_by_lane: dict[str, int] = field(default_factory=dict)

    def reserve(self, prompt: str, *, lane: Lane = "general") -> None:
        verification = min(2, max(0, self.max_model_calls - 1))
        investigation = min(4, max(0, self.max_model_calls - verification - 1))
        held = 0
        if lane in {"discovery", "investigation"}:
            held += max(0, verification - self.calls_by_lane.get("verification", 0))
        if lane == "discovery":
            held += max(0, investigation - self.calls_by_lane.get("investigation", 0))
        if (self.calls >= self.max_model_calls - held or self.prompt_chars + len(prompt) > self.max_prompt_chars
                or time.monotonic() - self.started >= self.max_wall_seconds):
            raise BudgetExceeded(f"review model budget exhausted for {lane}")
        self.calls += 1
        self.prompt_chars += len(prompt)
        self.calls_by_lane[lane] = self.calls_by_lane.get(lane, 0) + 1

    def to_dict(self) -> dict:
        return {"calls": self.calls, "prompt_chars": self.prompt_chars, "calls_by_lane": dict(self.calls_by_lane),
                "elapsed_seconds": time.monotonic() - self.started,
                "max_model_calls": self.max_model_calls, "max_prompt_chars": self.max_prompt_chars,
                "max_wall_seconds": self.max_wall_seconds}
