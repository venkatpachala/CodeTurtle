"""Deterministic defect qualification. LLM does not set status."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Optional

from core.agent.contract import is_hedge, proof_complete
from core.runtime.models import Candidate

VERIFIED_BUG = "VERIFIED_BUG"
PLAUSIBLE_BUT_UNPROVEN = "PLAUSIBLE_BUT_UNPROVEN"
DISPROVED = "DISPROVED"
NOT_A_DEFECT = "NOT_A_DEFECT"

_XOR_CLAIM = re.compile(
    r"(?i)exactly one|one of .+ or |provide (exactly )?one|task_path.+task_ref"
)
_XOR_CODE = re.compile(
    r"(?i)(raise\s+ValueError|if\s*\(.*is None\)\s*==\s*\(.*is None\))"
)
_MISSING_ERR = re.compile(r"(?i)missing error handling|handle missing|should handle")
_ERROR_PRINT = re.compile(r"(?i)(console\.print\(\s*[\"']Error|[\"']Error:|raise\s+\w*Error)")
_MISSING_GUARD = re.compile(r"(?i)missing guard|potential missing guard|guard (was )?removed")
_IF_NOT = re.compile(r"(?i)if\s+not\s+\w+")
_VIOLATION = re.compile(
    r"(?i)\b(would|will fail|when empty|if none|crash|leak|wrong|accepted|unguarded)\b"
)
_INVARIANT_TONE = re.compile(r"(?i)\b(should|must|exactly one|is required)\b")
_CONSUMER = re.compile(r"(?i)\b(submit|persist|write|save|store|dispatch|enqueue)\b")
_DISPLAY = re.compile(r"(?i)\b(display|print|tooltip|label|render|summary|ui)\b")


@dataclass
class QualifiedFinding:
    status: str
    file: str = ""
    start_line: int = 0
    end_line: int = 0
    symbol: str = ""
    claim: str = ""
    existing_code: str = ""
    invariant: str = ""
    violating_condition: str = ""
    execution_path: List[str] = field(default_factory=list)
    counter_evidence: List[str] = field(default_factory=list)
    reason: str = ""


def _blob(cand: Candidate) -> str:
    return f"{cand.title or ''} {cand.claim or ''} {cand.invariant or ''}"


def _code(cand: Candidate, extra: str = "") -> str:
    return f"{cand.existing_code or ''}\n{extra or ''}"


def _has_consumer(cand: Candidate) -> bool:
    path = [str(s).strip() for s in (cand.execution_path or []) if str(s).strip()]
    if len(path) >= 2:
        return True
    joined = " ".join(path).lower()
    text = f"{cand.claim or ''} {cand.actual or ''} {cand.violating_condition or ''} {joined}"
    if _CONSUMER.search(text):
        return True
    if _VIOLATION.search(text):
        return True
    return False


def _title_is_invariant_not_violation(cand: Candidate) -> bool:
    blob = _blob(cand)
    if _VIOLATION.search(blob):
        return False
    return bool(_INVARIANT_TONE.search(blob))


def qualify_finding(cand: Candidate, hunk: str = "") -> QualifiedFinding:
    """No LLM. Ask where the violation is, not whether the concern is plausible."""
    code = _code(cand, hunk)
    claim = _blob(cand)
    base = QualifiedFinding(
        status=PLAUSIBLE_BUT_UNPROVEN,
        file=str(cand.file or ""),
        start_line=int(cand.start_line or 0),
        symbol=str(cand.symbol or ""),
        claim=str(cand.claim or ""),
        existing_code=str(cand.existing_code or ""),
        invariant=str(cand.invariant or ""),
        violating_condition=str(cand.violating_condition or ""),
        execution_path=list(cand.execution_path or []),
        counter_evidence=list(cand.counter_evidence or []),
    )
    if not proof_complete(cand.to_dict() if hasattr(cand, "to_dict") else {}):
        base.status = PLAUSIBLE_BUT_UNPROVEN
        base.reason = "incomplete_proof"
        return base
    if is_hedge(cand.title, cand.claim, getattr(cand, "confidence", None)):
        base.status = PLAUSIBLE_BUT_UNPROVEN
        base.reason = "unproven"
        return base
    if _XOR_CLAIM.search(claim) and _XOR_CODE.search(code):
        base.status = NOT_A_DEFECT
        base.reason = "not_a_defect"
        return base
    if _MISSING_ERR.search(claim) and _ERROR_PRINT.search(code):
        base.status = NOT_A_DEFECT
        base.reason = "not_a_defect"
        return base
    if _MISSING_GUARD.search(claim) and _IF_NOT.search(code):
        base.status = NOT_A_DEFECT
        base.reason = "not_a_defect"
        return base
    if _title_is_invariant_not_violation(cand) and _ERROR_PRINT.search(code):
        base.status = NOT_A_DEFECT
        base.reason = "not_a_defect"
        return base
    if not _has_consumer(cand):
        base.status = PLAUSIBLE_BUT_UNPROVEN
        base.reason = "unproven"
        return base
    if _DISPLAY.search(claim) and not _CONSUMER.search(claim):
        base.status = PLAUSIBLE_BUT_UNPROVEN
        base.reason = "unproven"
        return base
    base.status = PLAUSIBLE_BUT_UNPROVEN
    base.reason = "plausible"
    return base
