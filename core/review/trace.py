"""core/review/trace.py — Pipeline telemetry for benchmark failure analysis.

Every candidate that enters the review pipeline gets a PipelineEvent at each
stage where it is either kept or dropped. This makes it possible to trace
exactly where a golden benchmark issue was lost.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


# Stage names
STAGE_CLASSIFY = "classify"         # kind != defect
STAGE_PROOF = "proof"              # proof_complete() check
STAGE_REFLECTOR = "reflector"      # reflect_candidate()
STAGE_POSITIONER = "positioner"    # position_candidate() / no_line
STAGE_VERIFIER = "verifier"        # verify_loop
STAGE_SANDBOX = "sandbox"          # execution evidence
STAGE_FINAL = "final"             # survived everything

# Status values
STATUS_KEPT = "kept"
STATUS_DROPPED = "dropped"


@dataclass
class PipelineEvent:
    """One recorded step in the candidate's journey through the review pipeline."""
    candidate_id: str              # C-001 … C-NNN (sequential within PR)
    stage: str                     # classify | proof | reflector | positioner | verifier | final
    status: str                    # kept | dropped
    file: str = ""
    line: Optional[int] = None
    title: str = ""
    drop_reason: Optional[str] = None   # incomplete_proof | no_line | not_a_defect | hedge | snippet_not_in_hunk | …
    detail: str = ""               # extra context (e.g. the reason string from reflector)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "stage": self.stage,
            "status": self.status,
            "file": self.file,
            "line": self.line,
            "title": self.title,
            "drop_reason": self.drop_reason,
            "detail": self.detail,
        }


@dataclass
class PipelineTrace:
    """Full trace of all candidates for a single PR review."""
    events: List[PipelineEvent] = field(default_factory=list)
    _counter: int = field(default=0, repr=False, compare=False)

    def next_candidate_id(self) -> str:
        """Allocate the next sequential candidate ID (C-001, C-002, …)."""
        self._counter += 1
        return f"C-{self._counter:03d}"

    def record(
        self,
        candidate_id: str,
        stage: str,
        status: str,
        *,
        file: str = "",
        line: Optional[int] = None,
        title: str = "",
        drop_reason: Optional[str] = None,
        detail: str = "",
    ) -> None:
        self.events.append(PipelineEvent(
            candidate_id=candidate_id,
            stage=stage,
            status=status,
            file=file,
            line=line,
            title=title,
            drop_reason=drop_reason,
            detail=detail,
        ))

    def drop(self, candidate_id: str, stage: str, reason: str, cand: Any = None) -> None:
        """Convenience: record a drop event."""
        self.record(
            candidate_id,
            stage=stage,
            status=STATUS_DROPPED,
            file=str(getattr(cand, "file", "") or "") if cand else "",
            title=str(getattr(cand, "title", "") or "") if cand else "",
            drop_reason=reason,
        )

    def keep(self, candidate_id: str, stage: str, cand: Any = None, line: Optional[int] = None) -> None:
        """Convenience: record a keep event."""
        self.record(
            candidate_id,
            stage=stage,
            status=STATUS_KEPT,
            file=str(getattr(cand, "file", "") or "") if cand else "",
            line=line,
            title=str(getattr(cand, "title", "") or "") if cand else "",
        )

    def summary(self) -> Dict[str, Any]:
        """Aggregate counts by stage and status."""
        stages: Dict[str, Dict[str, int]] = {}
        for ev in self.events:
            stages.setdefault(ev.stage, {"kept": 0, "dropped": 0})
            stages[ev.stage][ev.status] = stages[ev.stage].get(ev.status, 0) + 1
        drop_reasons: Dict[str, int] = {}
        for ev in self.events:
            if ev.drop_reason:
                drop_reasons[ev.drop_reason] = drop_reasons.get(ev.drop_reason, 0) + 1
        return {
            "total_candidates": self._counter,
            "final_findings": sum(
                1 for ev in self.events if ev.stage == STAGE_FINAL and ev.status == STATUS_KEPT
            ),
            "stages": stages,
            "drop_reasons": drop_reasons,
        }

    def to_list(self) -> List[Dict[str, Any]]:
        return [ev.to_dict() for ev in self.events]
