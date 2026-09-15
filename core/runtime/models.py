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
    severity: str = "medium"
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

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def comment_from_candidate(cand: Candidate, line: int) -> Comment:
    return Comment(
        bundle_id=cand.bundle_id,
        file=cand.file,
        symbol=cand.symbol,
        start_line=int(cand.start_line or 0),
        title=cand.title,
        claim=cand.claim,
        severity=cand.severity,
        source=cand.source,
        evidence_paths=list(cand.evidence_paths or []),
        line=int(line),
        verification="supported",
        kind=str(cand.kind or "defect"),
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
