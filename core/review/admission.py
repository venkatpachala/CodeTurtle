"""Deterministic investigation priority, never a defect verdict."""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Any


def get(unit: Any, key: str, default: Any = "") -> Any:
    return unit.get(key, default) if isinstance(unit, dict) else getattr(unit, key, default)


@dataclass(frozen=True)
class Priority:
    score: int
    reasons: tuple[str, ...]


def priority(unit: Any) -> Priority:
    kind = get(unit, "kind")
    if kind not in {"source", "test"}:
        return Priority(-100, ("non_executable_change",))
    changed = [line for line in str(get(unit, "excerpt")).splitlines()
               if line[:1] in {"+", "-"} and not line.startswith(("+++", "---"))]
    bodies = [line[1:].strip() for line in changed if line[1:].strip()]
    declaration = re.compile(r"^(?:from\s|import\s|(?:pub(?:\([^)]*\))?\s+)?(?:use|mod)\s|export\s+(?:type|\{))")
    if bodies and all(declaration.match(line) for line in bodies):
        return Priority(-10, ("import_or_module_declarations",))
    score = 10 if kind == "source" else 3
    reasons = ["source_behavior" if kind == "source" else "test_behavior"]
    controls = re.compile(r"\b(?:if|unless|match|raise|throw|return|await|delete|commit|rollback|lock|authorize|authenticate)\b")
    if any(line.startswith("-") and controls.search(line[1:]) for line in changed):
        score += 12
        reasons.append("removed_control_or_effect")
    if any(controls.search(line) for line in bodies):
        score += 4
        reasons.append("control_or_effect_change")
    hint = get(unit, "risk_hint", "none")
    if hint in {"mutation", "io"}:
        score += 8 if hint == "mutation" else 4
        reasons.append(hint)
    return Priority(score, tuple(reasons))


def plan_admission(units: list, *, max_units: int = 8, max_chars: int = 9500) -> tuple[list, list[dict]]:
    ranked = sorted(enumerate(units), key=lambda pair: (-priority(pair[1]).score, pair[0]))
    selected, records, used = [], [], 0
    for _, unit in ranked:
        item = priority(unit)
        text = str(get(unit, "excerpt"))
        reason = ("non_executable_change" if item.score == -100 else "excerpt_limit" if len(text) > 2500
                  else "unit_limit" if len(selected) >= max_units else "character_limit" if used+len(text) > max_chars else "selected")
        if reason == "selected":
            selected.append(unit)
            used += len(text)
        records.append({"unit_id": str(get(unit, "id")), "path": str(get(unit, "path")),
                        **asdict(item), "selected": reason == "selected", "reason": reason})
    return selected, records
