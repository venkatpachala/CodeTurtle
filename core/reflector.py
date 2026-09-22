"""Drop unsupported candidates. KEEP only grounded claims."""

from __future__ import annotations

import re
from typing import Iterable, List, Optional, Set, Tuple

from core.agent.contract import (
    has_failure_mode,
    is_changelog_title,
    is_hedge,
    is_test_name_restatement,
    proof_complete,
)
from core.change_units import _TEST_BASENAME_RE
from core.graphctx.symbols import is_valid_symbol
from core.pr_facts import normalize_path
from core.runtime.models import Candidate
from core.verification.diff_index import DiffIndex

STOPWORDS = {
    "name",
    "value",
    "test",
    "file",
    "code",
    "agent",
    "trial",
    "data",
    "type",
    "config",
    "the",
    "and",
}

_TEST_FOR_RE = re.compile(r"(?i)test for")
_TOKEN_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_GROUND_TOKEN_RE = re.compile(r"[A-Za-z0-9_]+")


def _is_test_path(path: str) -> bool:
    n = normalize_path(path)
    base = n.split("/")[-1]
    if _TEST_BASENAME_RE.match(base or ""):
        return True
    low = f"/{n.lower()}/"
    return "/tests/" in low or n.lower().startswith("tests/")


def _files_set(files_changed: Iterable[str]) -> Set[str]:
    return {normalize_path(p) for p in (files_changed or []) if p}


def _in_pr(path: str, allowed: Set[str], index: Optional[DiffIndex]) -> bool:
    n = normalize_path(path)
    if not n:
        return False
    if n in allowed:
        return True
    base = n.split("/")[-1]
    if base and any(a.split("/")[-1] == base for a in allowed):
        return True
    if index is not None and index.has_file(n):
        return True
    return False


def _hunk_blob(index: Optional[DiffIndex], path: str) -> str:
    if index is None:
        return ""
    parts: List[str] = []
    for h in index.hunks_for(path):
        parts.append(h.added or "")
        parts.append(h.body or "")
        parts.append(h.removed or "")
    return "\n".join(parts)


def _looks_like_path_or_py(symbol: str) -> bool:
    s = (symbol or "").strip()
    if not s:
        return False
    return not is_valid_symbol(s)


def _distinctive_tokens(text: str) -> List[str]:
    out: List[str] = []
    seen = set()
    for tok in _TOKEN_RE.findall(text or ""):
        low = tok.lower()
        if len(tok) < 5 or low in STOPWORDS:
            continue
        if low in seen:
            continue
        seen.add(low)
        out.append(tok)
    return out


def _grounding_tokens(text: str) -> Set[str]:
    """Tokens suitable for tying an exact code quote to the stated defect."""
    out: Set[str] = set()
    for token in _GROUND_TOKEN_RE.findall(text or ""):
        low = token.lower()
        if low in STOPWORDS:
            continue
        # Preserve compact literals such as 10MB; otherwise require enough
        # characters to avoid accepting punctuation and language keywords.
        if any(ch.isdigit() for ch in low) or len(low) >= 4:
            out.add(low)
    return out


def reflect_candidate(
    candidate: Candidate,
    *,
    files_changed: Iterable[str],
    index: Optional[DiffIndex] = None,
    line: Optional[int] = None,
    bundle_paths: Optional[Iterable[str]] = None,
) -> Tuple[bool, str]:
    """Return (keep, reason). DROP rules are numbered in the v4 spec."""
    allowed = _files_set(files_changed)
    path = normalize_path(candidate.file)

    def _drop(reason: str) -> Tuple[bool, str]:
        print(
            f"[Reflector] DROP reason={reason} file={path} "
            f"title={candidate.title!r} symbol={candidate.symbol!r}"
        )
        return False, reason

    if str(getattr(candidate, "kind", "") or "").lower() == "note":
        return _drop("note")

    title = candidate.title or ""
    claim = candidate.claim or ""
    if is_changelog_title(title):
        return _drop("changelog")
    if is_test_name_restatement(title, claim):
        return _drop("test_restatement")

    if str(getattr(candidate, "kind", "") or "defect") == "defect":
        payload = candidate.to_dict() if hasattr(candidate, "to_dict") else {}
        if not proof_complete(payload):
            return _drop("incomplete_proof")

    conf = getattr(candidate, "confidence", None)
    if is_hedge(title, claim, conf):
        candidate.severity = "nit"
        if hasattr(candidate, "verify_status"):
            candidate.verify_status = "uncertain"

    if not _in_pr(path, allowed, index):
        return _drop("file_not_in_pr")

    if bundle_paths is not None:
        bset = {normalize_path(p) for p in bundle_paths if p}
        if bset and not _in_pr(path, bset, None):
            return _drop("off_bundle")

    if _TEST_FOR_RE.search(title) and not _is_test_path(path):
        return _drop("test_for_on_nontest")

    for ep in candidate.evidence_paths or []:
        if not _in_pr(str(ep), allowed, index):
            return _drop("evidence_not_in_pr")

    if candidate.symbol and _looks_like_path_or_py(candidate.symbol):
        return _drop("symbol_is_path")

    if not line:
        return _drop("no_line")

    blob = _hunk_blob(index, path)
    blob_l = blob.lower()
    if candidate.symbol and candidate.symbol.lower() in blob_l:
        return True, "symbol_in_hunk"

    tokens = _distinctive_tokens(f"{candidate.title or ''} {candidate.claim or ''}")
    hits = [t for t in tokens if t.lower() in blob_l]
    if len(hits) >= 2:
        return True, "token_overlap"

    # The proof stage must quote ``existing_code`` from an added line.  Accept
    # that strong anchor when at least one substantive identifier or literal
    # also occurs in the defect statement.  This handles code/prose forms such
    # as ``maxSizeKB`` and "10MB" without allowing unrelated boilerplate.
    existing = " ".join((candidate.existing_code or "").split()).lstrip("+-").strip()
    normalized_blob = " ".join(blob.split())
    # Require the user-facing defect statement itself to connect to the code;
    # invariant/actual fields are easier for a model to fill generically.
    statement = f"{candidate.title or ''} {candidate.claim or ''}"
    if (
        existing
        and existing in normalized_blob
        and (_grounding_tokens(existing) & _grounding_tokens(statement))
    ):
        return True, "snippet_in_hunk"

    return _drop("stopword_only")
