"""core/review/finding.py — The single canonical finding object for CodeTurtle v4.

One ReviewFinding drives:
  - Terminal display
  - GitHub review comment
  - Benchmark evaluation JSON
  - Internal pipeline telemetry

Never create parallel finding representations elsewhere.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


# Severity levels (ordered most → least severe)
SEVERITY_CRITICAL = "critical"
SEVERITY_HIGH = "high"
SEVERITY_MEDIUM = "medium"
SEVERITY_LOW = "low"

# Verification states
VERIFICATION_VERIFIED = "verified"
VERIFICATION_UNCERTAIN = "uncertain"
VERIFICATION_DISPROVED = "disproved"
VERIFICATION_CANDIDATE = "candidate"

# Execution statuses
EXEC_NOT_RUN = "NOT_RUN"
EXEC_PASSED = "PASSED"
EXEC_FAILED = "FAILED"
EXEC_TIMEOUT = "TIMEOUT"
EXEC_INSTALL_FAILED = "INSTALL_FAILED"
EXEC_SKIPPED = "SKIPPED"


@dataclass
class ExecutionEvidence:
    """Sandbox test execution result attached to a finding as evidence."""
    status: str = EXEC_NOT_RUN          # NOT_RUN | PASSED | FAILED | TIMEOUT | INSTALL_FAILED | SKIPPED
    sandbox: bool = True
    environment: str = ""               # uv | venv | system
    command: str = ""                   # e.g. "pytest tests/test_orders.py"
    exit_code: Optional[int] = None
    passed: Optional[int] = None
    failed: Optional[int] = None
    duration_seconds: Optional[float] = None
    failed_tests: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status,
            "sandbox": self.sandbox,
            "environment": self.environment,
            "command": self.command,
            "exit_code": self.exit_code,
            "passed": self.passed,
            "failed": self.failed,
            "duration_seconds": self.duration_seconds,
            "failed_tests": list(self.failed_tests),
        }


@dataclass
class ReviewFinding:
    """Canonical code-review finding for CodeTurtle v4.

    This is the single source of truth for any finding produced by the review
    pipeline. All output adapters (GitHub, benchmark, terminal, JSON) read from
    this object — never from intermediate Candidate or Comment dictionaries.
    """

    # ── Identity ────────────────────────────────────────────────────────────
    id: str                             # F-001, F-002, … (sequential per PR)

    # ── Core content ────────────────────────────────────────────────────────
    title: str
    claim: str

    # ── Location ────────────────────────────────────────────────────────────
    file: str
    line: Optional[int]                 # None when line cannot be determined

    # ── Classification ──────────────────────────────────────────────────────
    severity: str = SEVERITY_MEDIUM     # critical | high | medium | low
    category: str = "bug"              # bug | api | concurrency | perf | style | test_gap | doc_defect | security

    # ── Confidence & evidence ───────────────────────────────────────────────
    confidence: float = 0.5
    evidence: List[str] = field(default_factory=list)
    execution_path: List[str] = field(default_factory=list)

    # ── Code proof fields (from BundleAgent) ────────────────────────────────
    existing_code: str = ""
    invariant: str = ""
    violating_condition: str = ""
    expected: str = ""
    actual: str = ""

    # ── Verification ────────────────────────────────────────────────────────
    verification_status: str = VERIFICATION_CANDIDATE
    execution: Optional[ExecutionEvidence] = None   # sandbox evidence; never gates the finding

    # ── Tracing ─────────────────────────────────────────────────────────────
    bundle_id: Optional[str] = None
    candidate_id: Optional[str] = None   # C-NNN for pipeline trace correlation
    source: str = "llm"                  # llm | rule

    # ── Related tests discovered during bundling ─────────────────────────────
    related_tests: List[str] = field(default_factory=list)

    # ────────────────────────────────────────────────────────────────────────
    # Output adapters
    # ────────────────────────────────────────────────────────────────────────

    def render_comment(self) -> str:
        """Human-readable markdown comment body."""
        parts = [f"**{self.title}**", ""]
        parts.append(self.claim)

        if self.invariant:
            parts.extend(["", f"**Invariant violated:** {self.invariant}"])
        if self.violating_condition:
            parts.append(f"**When:** {self.violating_condition}")
        if self.existing_code:
            parts.extend(["", "**Relevant code:**", "```", self.existing_code.strip(), "```"])
        if self.expected and self.actual:
            parts.extend([
                "",
                f"**Expected:** {self.expected}",
                f"**Actual:** {self.actual}",
            ])
        if self.execution_path:
            parts.extend(["", f"**Call path:** `{'` → `'.join(self.execution_path)}`"])
        if self.evidence:
            parts.extend(["", f"**Evidence:** {', '.join(self.evidence)}"])

        # Metadata footer
        parts.extend([
            "",
            f"*Severity: {self.severity} · Confidence: {int(self.confidence * 100)}% · "
            f"Verified: {self.verification_status}*",
        ])
        return "\n".join(parts)

    def to_github_comment(self) -> Dict[str, Any]:
        """Format for GitHub PR review comment API."""
        return {
            "path": self.file,
            "line": self.line,
            "body": self.render_comment(),
        }

    def to_benchmark_comment(self) -> Dict[str, Any]:
        """Format for benchmark evaluation (path + line + body)."""
        return {
            "path": self.file,
            "line": self.line,
            "body": self.render_comment(),
        }

    def to_dict(self) -> Dict[str, Any]:
        """Full serialisation for JSON output / prediction schema."""
        return {
            "id": self.id,
            "title": self.title,
            "claim": self.claim,
            "file": self.file,
            "line": self.line,
            "severity": self.severity,
            "category": self.category,
            "confidence": round(self.confidence, 3),
            "evidence": list(self.evidence),
            "execution_path": list(self.execution_path),
            "existing_code": self.existing_code,
            "invariant": self.invariant,
            "violating_condition": self.violating_condition,
            "expected": self.expected,
            "actual": self.actual,
            "verification_status": self.verification_status,
            "execution": self.execution.to_dict() if self.execution else None,
            "bundle_id": self.bundle_id,
            "candidate_id": self.candidate_id,
            "source": self.source,
            "related_tests": list(self.related_tests),
        }

    @classmethod
    def from_candidate_and_comment(
        cls,
        cand: Any,
        line: int,
        *,
        finding_id: str = "",
        candidate_id: str = "",
    ) -> "ReviewFinding":
        """Promote a verified Candidate+line into a ReviewFinding.

        This is the single conversion point. Never build ReviewFinding
        from raw dict lookups elsewhere.
        """
        fid = finding_id or f"F-{uuid.uuid4().hex[:6].upper()}"
        verify_status = str(getattr(cand, "verify_status", "") or VERIFICATION_CANDIDATE)
        # Map internal verify_status onto canonical verification_status
        status_map = {
            "verified": VERIFICATION_VERIFIED,
            "uncertain": VERIFICATION_UNCERTAIN,
            "disproved": VERIFICATION_DISPROVED,
            "candidate": VERIFICATION_CANDIDATE,
        }
        verification_status = status_map.get(verify_status, VERIFICATION_UNCERTAIN)

        return cls(
            id=fid,
            title=str(getattr(cand, "title", "") or ""),
            claim=str(getattr(cand, "claim", "") or ""),
            file=str(getattr(cand, "file", "") or ""),
            line=int(line) if line else None,
            severity=str(getattr(cand, "severity", SEVERITY_MEDIUM) or SEVERITY_MEDIUM),
            category=_infer_category(cand),
            confidence=float(getattr(cand, "confidence", 0.5) or 0.5),
            evidence=list(getattr(cand, "evidence", None) or []),
            execution_path=list(getattr(cand, "execution_path", None) or []),
            existing_code=str(getattr(cand, "existing_code", "") or ""),
            invariant=str(getattr(cand, "invariant", "") or ""),
            violating_condition=str(getattr(cand, "violating_condition", "") or ""),
            expected=str(getattr(cand, "expected", "") or ""),
            actual=str(getattr(cand, "actual", "") or ""),
            verification_status=verification_status,
            execution=None,
            bundle_id=str(getattr(cand, "bundle_id", "") or "") or None,
            candidate_id=candidate_id or None,
            source=str(getattr(cand, "source", "llm") or "llm"),
        )


def _infer_category(cand: Any) -> str:
    """Infer benchmark category from candidate fields.

    Mapping is best-effort. The LLM does not produce category; we infer from
    title/claim keywords. Can be refined with a config table later.
    """
    text = " ".join([
        str(getattr(cand, "title", "") or ""),
        str(getattr(cand, "claim", "") or ""),
        str(getattr(cand, "violating_condition", "") or ""),
    ]).lower()

    if any(k in text for k in ("concurren", "race condition", "thread", "deadlock", "async", "lock")):
        return "concurrency"
    if any(k in text for k in ("security", "inject", "xss", "csrf", "auth", "unauthori", "permission")):
        return "security"
    if any(k in text for k in ("performance", "n+1", "slow", "latency", "timeout", "cache miss")):
        return "perf"
    if any(k in text for k in ("api", "contract", "interface", "signature", "return type", "null")):
        return "api"
    if any(k in text for k in ("test", "coverage", "assert", "mock", "fixture")):
        return "test_gap"
    if any(k in text for k in ("doc", "comment", "docstring", "readme", "translation", "locale")):
        return "doc_defect"
    if any(k in text for k in ("style", "naming", "typo", "format", "unused")):
        return "style"
    return "bug"
