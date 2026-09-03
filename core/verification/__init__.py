"""Phase 4 — prove claims against the diff (hunk-level first)."""

from core.verification.diff_index import DiffIndex, Hunk, build_diff_index
from core.verification.hunk_verifier import verify_finding, verify_findings
from core.verification.models import VerificationRecord, VerificationStatus
from core.verification.policy import recommendation_from_verification

__all__ = [
    "DiffIndex",
    "Hunk",
    "VerificationRecord",
    "VerificationStatus",
    "build_diff_index",
    "recommendation_from_verification",
    "verify_finding",
    "verify_findings",
]
