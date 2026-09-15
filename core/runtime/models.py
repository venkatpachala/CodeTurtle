"""V4 review runtime models. No LLM decision fields."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class Bundle:
    id: str
    paths: List[str] = field(default_factory=list)
    units: List[Any] = field(default_factory=list)
    symbols: List[str] = field(default_factory=list)
    kind: str = "source"

    def to_dict(self) -> Dict[str, Any]:
        units = []
        for u in self.units:
            if hasattr(u, "model_dump"):
                units.append(u.model_dump())
            elif isinstance(u, dict):
                units.append(dict(u))
            else:
                units.append(u)
        return {
            "id": self.id,
            "paths": list(self.paths),
            "units": units,
            "symbols": list(self.symbols),
            "kind": self.kind,
        }


@dataclass
class Candidate:
    bundle_id: str
    file: str
    symbol: str = ""
    start_line: int = 0
    title: str = ""
    claim: str = ""
    existing_code: str = ""
    invariant: str = ""
    violating_condition: str = ""
    expected: str = ""
    actual: str = ""
    execution_path: List[str] = field(default_factory=list)
    evidence: List[str] = field(default_factory=list)
    counter_evidence: List[str] = field(default_factory=list)
    verify_status: str = "candidate"  # candidate|verified|disproved|uncertain
    severity: str = "medium"
    confidence: float = 0.5
    source: str = "agent"  # agent | rule
    evidence_paths: List[str] = field(default_factory=list)
    kind: str = "defect"  # defect | note

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class Comment:
    bundle_id: str
    file: str
    symbol: str = ""
    start_line: int = 0
    title: str = ""
    claim: str = ""
    severity: str = "medium"
    source: str = "agent"
    evidence_paths: List[str] = field(default_factory=list)
    line: int = 0
    verification: str = "supported"
    kind: str = "defect"
    tests_run: bool = False
    existing_code: str = ""
    invariant: str = ""
    violating_condition: str = ""
    expected: str = ""
    actual: str = ""
    execution_path: List[str] = field(default_factory=list)
    evidence: List[str] = field(default_factory=list)
    counter_evidence: List[str] = field(default_factory=list)
    verify_status: str = "candidate"
    confidence: float = 0.5

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def comment_from_candidate(cand: Candidate, line: int) -> Comment:
    status = str(getattr(cand, "verify_status", "") or "candidate")
    verification = {
        "verified": "supported",
        "uncertain": "uncertain",
        "disproved": "unsupported",
    }.get(status, "supported")
    return Comment(
        bundle_id=cand.bundle_id,
        file=cand.file,
        symbol=cand.symbol,
        start_line=int(cand.start_line or 0),
        title=cand.title,
        claim=cand.claim,
        severity=cand.severity,
        source=cand.source,
        evidence_paths=list(cand.evidence_paths or cand.evidence or []),
        line=int(line),
        verification=verification,
        kind=str(cand.kind or "defect"),
        existing_code=str(getattr(cand, "existing_code", "") or ""),
        invariant=str(getattr(cand, "invariant", "") or ""),
        violating_condition=str(getattr(cand, "violating_condition", "") or ""),
        expected=str(getattr(cand, "expected", "") or ""),
        actual=str(getattr(cand, "actual", "") or ""),
        execution_path=list(getattr(cand, "execution_path", None) or []),
        evidence=list(getattr(cand, "evidence", None) or []),
        counter_evidence=list(getattr(cand, "counter_evidence", None) or []),
        verify_status=status,
        confidence=float(getattr(cand, "confidence", 0.5) or 0.5),
    )


@dataclass
class ReviewResult:
    decision: str = "COMMENT"
    policy_reason: str = ""
    comments: List[Comment] = field(default_factory=list)
    dropped: List[Dict[str, Any]] = field(default_factory=list)
    bundles: List[Bundle] = field(default_factory=list)
    coverage: Dict[str, Any] = field(default_factory=dict)
    execution: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "decision": self.decision,
            "policy_reason": self.policy_reason,
            "comments": [c.to_dict() for c in self.comments],
            "dropped": list(self.dropped),
            "bundles": [b.to_dict() for b in self.bundles],
            "coverage": dict(self.coverage or {}),
            "execution": dict(self.execution or {}),
        }
