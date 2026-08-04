from __future__ import annotations

from dataclasses import dataclass, field
from typing import List


@dataclass
class Check:
    name: str
    passed: bool
    detail: str = ""


@dataclass
class PhaseReport:
    phase: str
    checks: List[Check] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return all(c.passed for c in self.checks)

    def add(self, name: str, passed: bool, detail: str = ""):
        self.checks.append(Check(name, passed, detail))

    def print(self):
        status = "PASS" if self.ok else "FAIL"
        print(f"\n=== {self.phase}: {status} ===")
        for c in self.checks:
            mark = "✓" if c.passed else "✗"
            print(f"  {mark} {c.name}" + (f" — {c.detail}" if c.detail else ""))
        print(f"Score: {sum(1 for c in self.checks if c.passed)}/{len(self.checks)}")