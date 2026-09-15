"""Defect-only review contract. Changelog / restated tests are not findings."""

from __future__ import annotations

import re
from typing import Any, Dict, Optional

CHANGELOG_TITLE_RE = re.compile(
    r"(?i)^(add|adds|added|implement|update|refactor|test )\b"
)
TEST_SENTENCE_RE = re.compile(r"(?i)^test[s]? [a-z]")
TEST_FUNC_RE = re.compile(r"^test_[A-Za-z0-9_]+$")
FAILURE_TOKEN_RE = re.compile(
    r"(?i)\b(fail|fails|failed|miss|missing|not|wrong|leak|crash|break|broken|empty)\b"
)


def has_failure_mode(text: str) -> bool:
    return bool(FAILURE_TOKEN_RE.search(text or ""))


def is_changelog_title(title: str) -> bool:
    t = (title or "").strip()
    if not t:
        return False
    return bool(CHANGELOG_TITLE_RE.search(t) or TEST_SENTENCE_RE.search(t))


def is_test_func_title(title: str) -> bool:
    t = (title or "").strip()
    if TEST_FUNC_RE.match(t):
        return True
    snake = re.sub(r"[^A-Za-z0-9]+", "_", t).strip("_").lower()
    return bool(TEST_FUNC_RE.match(snake))


def is_test_name_restatement(title: str, claim: str = "") -> bool:
    t = (title or "").strip()
    if TEST_SENTENCE_RE.search(t):
        return not has_failure_mode(f"{t} {claim or ''}")
    if is_test_func_title(t) and not has_failure_mode(f"{t} {claim or ''}"):
        return True
    return False


def classify_kind(
    title: str,
    claim: str = "",
    kind: Optional[str] = None,
) -> str:
    """defect | note. Changelog and restated test names are notes."""
    raw = str(kind or "").strip().lower()
    blob_title = (title or "").strip()
    blob_claim = (claim or "").strip()
    if is_changelog_title(blob_title) or is_test_name_restatement(blob_title, blob_claim):
        return "note"
    if raw == "note":
        return "note"
    return "defect"


def as_finding_kind(item: Dict[str, Any] | None) -> str:
    item = item or {}
    return classify_kind(
        str(item.get("title") or ""),
        str(item.get("claim") or item.get("description") or ""),
        str(item.get("kind") or "") or None,
    )
