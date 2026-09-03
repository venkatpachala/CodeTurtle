"""Score claim ↔ hunk text. Deterministic. No LLM."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

from core.pr_facts import normalize_path
from core.verification.diff_index import DiffIndex, Hunk, build_diff_index
from core.verification.models import VerificationRecord
from core.verification.policy import adjust_testing_nit
from core.verification.test_map import annotate_tests

_IDENT_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]{3,}")
_SCOPED_RE = re.compile(r"@[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")
_VERSION_RE = re.compile(r"\b\d+\.\d+(?:\.\d+)?\b")
_HYPHEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9]*(?:-[A-Za-z0-9_.]+)+")

_STOP = {
    "this", "that", "these", "those", "with", "from", "have", "has",
    "should", "would", "could", "must", "ensure", "ensures", "please",
    "there", "their", "about", "into", "also", "only", "just", "very",
    "more", "than", "then", "when", "where", "which", "what", "does",
    "doing", "done", "being", "been", "will", "shall", "might",
    "issue", "issues", "finding", "change", "changes", "changed",
    "update", "updates", "updated", "file", "files", "code", "function",
    "method", "class", "test", "tests", "testing", "need", "needs",
    "missing", "add", "adds", "added", "documentation", "comment",
    "comments", "naming", "clarity", "handling", "potential",
    "compatibility", "feature", "architecture", "support", "improve",
    "improves", "improvement", "review", "reviewed",
}

MIN_TOKEN_HITS = 2


def claim_tokens(finding: Dict[str, Any]) -> List[str]:
    """Identifiers from claim + title + symbol. Length ≥ 4, plus scoped pkgs / versions."""
    parts = [
        str(finding.get("claim") or ""),
        str(finding.get("title") or ""),
        str(finding.get("symbol") or ""),
        str(finding.get("description") or ""),
    ]
    blob = " ".join(parts)
    found: List[str] = []
    for rx in (_SCOPED_RE, _HYPHEN_RE, _VERSION_RE, _IDENT_RE):
        for m in rx.finditer(blob):
            tok = m.group(0)
            if tok.lower() in _STOP:
                continue
            found.append(tok)
    # de-dupe case-insensitively, keep first spelling
    out: List[str] = []
    seen: set[str] = set()
    for t in found:
        k = t.lower()
        if k in seen:
            continue
        seen.add(k)
        out.append(t)
    return out


def _hunks_or_file_patch(index: DiffIndex, path: str) -> List[Hunk]:
    hunks = index.hunks_for(path)
    if hunks:
        return hunks
    # Lockfile (or any file in the index) with no parsed @@ : no extra hops
    if index.has_file(path):
        return []
    return []


def _token_in_text(token: str, text: str) -> bool:
    if not token or not text:
        return False
    return token.lower() in text.lower()


def verify_finding(
    finding: Dict[str, Any],
    index: DiffIndex,
    *,
    files_changed: Optional[List[str]] = None,
) -> VerificationRecord:
    file_ = normalize_path(str(finding.get("file") or ""))
    rec = VerificationRecord(
        finding_id=str(finding.get("id") or ""),
        file=file_,
        title=str(finding.get("title") or ""),
        status="uncertain",
        reasons=[],
    )
    if not file_:
        rec.status = "unsupported"
        rec.reasons = ["missing_file"]
        return rec

    hunks = _hunks_or_file_patch(index, file_)
    in_diff = index.has_file(file_)
    if not hunks and not in_diff:
        rec.status = "unsupported"
        rec.reasons = ["no_hunk_for_file"]
        return rec

    # Lockfile with a file-level patch but odd headers: still search whole indexed body
    if not hunks and in_diff:
        rec.status = "uncertain"
        rec.reasons = ["no_hunk_for_file"]
        return rec

    rec.hunk_header = hunks[0].header if hunks else ""
    rec.hunk_excerpt = (hunks[0].body or "")[:800] if hunks else ""

    added_removed = "\n".join(
        (h.added or "") + "\n" + (h.removed or "") for h in hunks
    )
    body = "\n".join(h.body or "" for h in hunks)

    symbol = str(finding.get("symbol") or "").strip()
    if symbol and (
        index.contains(file_, symbol) or _token_in_text(symbol, body) or _token_in_text(symbol, added_removed)
    ):
        rec.status = "supported"
        rec.reasons = ["symbol_in_hunk"]
        rec.matched_tokens = [symbol]
        rec.hunk_header = next(
            (h.header for h in hunks if _token_in_text(symbol, h.body) or _token_in_text(symbol, h.added)),
            rec.hunk_header,
        )
        return rec

    start = finding.get("start_line")
    if start is not None and index.line_in_new_file(file_, start):
        rec.status = "supported"
        rec.reasons = ["line_in_hunk"]
        rec.matched_tokens = [f"line:{start}"]
        return rec

    tokens = claim_tokens(finding)
    hits = [t for t in tokens if _token_in_text(t, added_removed) or _token_in_text(t, body)]
    rec.matched_tokens = hits
    distinctive = [
        t
        for t in hits
        if t.startswith("@") or _VERSION_RE.fullmatch(t) or "-" in t
    ]
    if distinctive or len(hits) >= MIN_TOKEN_HITS:
        rec.status = "supported"
        rec.reasons = ["token_overlap"]
        hit_hunk = next(
            (h for h in hunks if any(_token_in_text(t, h.body) for t in hits)),
            hunks[0],
        )
        rec.hunk_header = hit_hunk.header
        rec.hunk_excerpt = (hit_hunk.body or "")[:800]
        return rec

    if in_diff or hunks:
        rec.status = "uncertain"
        rec.reasons = ["no_token_in_hunk"]
        return rec

    rec.status = "unsupported"
    rec.reasons = ["no_hunk_for_file"]
    return rec


def verify_findings(
    findings: List[Dict[str, Any]],
    full_diff: str,
    *,
    files_changed: Optional[List[str]] = None,
) -> Tuple[List[Dict[str, Any]], List[VerificationRecord]]:
    index = build_diff_index(full_diff or "")
    records: List[VerificationRecord] = []
    stamped: List[Dict[str, Any]] = []
    for f in findings or []:
        d = dict(f) if isinstance(f, dict) else {}
        rec = verify_finding(d, index, files_changed=files_changed)
        d["verification_status"] = rec.status
        d["verification_reasons"] = list(rec.reasons)
        d["hunk_excerpt"] = rec.hunk_excerpt
        d["hunk_header"] = rec.hunk_header
        d["matched_tokens"] = list(rec.matched_tokens)
        # 4.2 — does not change verification_status
        d = annotate_tests(d, files_changed or [])
        rec.tests_touched = bool(d.get("tests_touched"))
        rec.related_tests = list(d.get("related_tests") or [])
        d = adjust_testing_nit(d, bool(d.get("tests_touched")))
        if rec.status == "unsupported":
            # cannot be blocking-grade on its own
            sev = str(d.get("severity") or "").lower()
            if sev in ("blocking", "critical", "high", "medium", "concern"):
                d["severity"] = "nit"
        records.append(rec)
        stamped.append(d)
        _log_record(rec)
        _log_tests(rec)
    return stamped, records


def _log_record(rec: VerificationRecord) -> None:
    status = rec.status.upper()
    if rec.status == "supported":
        print(
            f"[Verify] SUPPORTED file={rec.file} "
            f"tokens={rec.matched_tokens} hunk={rec.hunk_header}"
        )
    else:
        reason = rec.reasons[0] if rec.reasons else rec.status
        print(f"[Verify] {status} file={rec.file} reason={reason}")


def _log_tests(rec: VerificationRecord) -> None:
    if rec.tests_touched:
        print(
            f"[Verify] tests_touched=true file={rec.file} tests={rec.related_tests}"
        )
    else:
        print(f"[Verify] tests_touched=false file={rec.file}")
