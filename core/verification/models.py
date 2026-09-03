"""Phase 4 verification records. KEEP ≠ proven."""

from __future__ import annotations

from typing import List, Literal, Optional

from pydantic import BaseModel, Field

VerificationStatus = Literal["supported", "unsupported", "uncertain"]


class VerificationRecord(BaseModel):
    finding_id: str = ""
    file: str = ""
    status: VerificationStatus = "uncertain"
    reasons: List[str] = Field(default_factory=list)
    hunk_header: str = ""
    hunk_excerpt: str = ""
    matched_tokens: List[str] = Field(default_factory=list)
    tests_touched: bool = False
    related_tests: List[str] = Field(default_factory=list)
    title: str = ""


class ExecutionSlice(BaseModel):
    """One language runner (python or js)."""

    skipped: bool = True
    skip_reason: Optional[str] = None
    cmd: str = ""
    cwd: str = ""
    exit_code: Optional[int] = None
    elapsed_s: float = 0.0
    passed: Optional[int] = None
    failed: Optional[int] = None
    failed_names: List[str] = Field(default_factory=list)
    raw_tail: str = ""
    ran_paths: List[str] = Field(default_factory=list)
    env: str = ""
    frozen: bool = False
    cached: bool = False
    install_cmd: str = ""
    install_elapsed_s: float = 0.0


class ExecutionRecord(BaseModel):
    enabled: bool = False
    skipped: bool = True
    skip_reason: Optional[str] = None
    cmd: str = ""
    cwd: str = ""
    exit_code: Optional[int] = None
    elapsed_s: float = 0.0
    passed: Optional[int] = None
    failed: Optional[int] = None
    failed_names: List[str] = Field(default_factory=list)
    raw_tail: str = ""
    ran_paths: List[str] = Field(default_factory=list)
    python_env: str = ""
    python: ExecutionSlice = Field(default_factory=ExecutionSlice)
    js: ExecutionSlice = Field(default_factory=ExecutionSlice)
