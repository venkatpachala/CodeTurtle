"""Shared bounded model work. Wall time is checked between calls."""
from __future__ import annotations

import time
from dataclasses import dataclass, field


class BudgetExceeded(RuntimeError):
    pass


@dataclass
class ReviewBudget:
    max_model_calls: int = 12
    max_prompt_chars: int = 120000
    max_wall_seconds: float = 300.0
    calls: int = 0
    prompt_chars: int = 0
    started: float = field(default_factory=time.monotonic)

    def reserve(self, prompt: str) -> None:
        if (self.calls >= self.max_model_calls or self.prompt_chars + len(prompt) > self.max_prompt_chars
                or time.monotonic() - self.started >= self.max_wall_seconds):
            raise BudgetExceeded("review model budget exhausted")
        self.calls += 1
        self.prompt_chars += len(prompt)

    def to_dict(self) -> dict:
        return {"calls": self.calls, "prompt_chars": self.prompt_chars,
                "elapsed_seconds": time.monotonic() - self.started,
                "max_model_calls": self.max_model_calls, "max_prompt_chars": self.max_prompt_chars,
                "max_wall_seconds": self.max_wall_seconds}
