"""Lightweight discovery objects for the active V4 review runtime.

Discovery intentionally does not require proof.  A hypothesis is an
investigation lead; only the later proof stage may create a Candidate.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class ReviewHypothesis:
    id: str
    bundle_id: str
    file: str
    observation: str
    hypothesis: str
    symbol: str = ""
    category: str = "correctness"
    why_investigate: str = ""
    required_evidence: list[str] = field(default_factory=list)
    confidence: float = 0.5

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def hypothesis_dict(raw: Any, *, bundle_id: str, index: int) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    file = str(raw.get("file") or raw.get("path") or "").replace("\\", "/").strip()
    observation = str(raw.get("observation") or "").strip()
    claim = str(raw.get("hypothesis") or raw.get("claim") or "").strip()
    if not file or not observation or not claim:
        return None
    requested = raw.get("required_evidence") or ["source", "callers", "tests"]
    if isinstance(requested, str):
        requested = [requested]
    allowed = {"source", "callers", "callees", "tests", "symbol"}
    evidence = [str(x).strip().lower() for x in requested if str(x).strip().lower() in allowed]
    try:
        confidence = max(0.0, min(1.0, float(raw.get("confidence", 0.5))))
    except (TypeError, ValueError):
        confidence = 0.5
    return {
        "id": str(raw.get("id") or f"H-{index:03d}"),
        "bundle_id": bundle_id,
        "file": file,
        "symbol": str(raw.get("symbol") or "").strip(),
        "category": str(raw.get("category") or "correctness").strip().lower(),
        "observation": observation,
        "hypothesis": claim,
        "why_investigate": str(raw.get("why_investigate") or "").strip(),
        "required_evidence": evidence or ["source"],
        "confidence": confidence,
    }
