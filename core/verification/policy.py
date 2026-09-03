"""How critic/final treat verification grades. Pure function — unit-tested."""

from __future__ import annotations

from typing import Any, Dict, List

MEDIUM_PLUS = {
    "medium",
    "concern",
    "high",
    "critical",
    "blocking",
}

_TEST_NIT_PHRASES = (
    "no test",
    "add test",
    "missing test",
    "test coverage",
    "untested",
    "without test",
    "lack of test",
    "please add test",
)


def looks_like_testing_nit(finding: Dict[str, Any] | None) -> bool:
    f = finding or {}
    blob = " ".join(
        [
            str(f.get("title") or ""),
            str(f.get("claim") or ""),
            str(f.get("description") or ""),
            str(f.get("reasoning") or ""),
        ]
    ).lower()
    return any(p in blob for p in _TEST_NIT_PHRASES)


def adjust_testing_nit(finding: Dict[str, Any], tests_touched: bool) -> Dict[str, Any]:
    """If a 'add tests' nit and the PR already touches related tests, downgrade severity.

    Does not change verification_status. Does not force REQUEST_CHANGES.
    """
    if not finding:
        return finding
    if not tests_touched:
        return finding
    if not looks_like_testing_nit(finding):
        return finding
    sev = str(finding.get("severity") or "").lower()
    if sev in MEDIUM_PLUS:
        finding["severity"] = "nit"
    finding["verification_notes"] = "related tests also changed in this PR"
    return finding


_STAMP_KEYS = (
    "verification_status",
    "verification_notes",
    "matched_tokens",
    "tests_touched",
    "related_tests",
    "tests_run",
    "tests_passed",
    "execution_summary",
)


def reattach_stamps(
    kept: List[Dict[str, Any]] | None,
    original: List[Dict[str, Any]] | None,
) -> List[Dict[str, Any]]:
    """Copy 4.1/4.2/4.3 evidence fields onto critic output (LLM schema drops them)."""
    def _as_d(f: Any) -> Dict[str, Any]:
        if isinstance(f, dict):
            return dict(f)
        if hasattr(f, "model_dump"):
            return f.model_dump()
        return {}

    orig = list(original or [])
    by_file: Dict[str, Dict[str, Any]] = {}
    by_title: Dict[str, Dict[str, Any]] = {}
    for f in orig:
        d0 = _as_d(f)
        if not d0:
            continue
        fp = str(d0.get("file") or "").replace("\\", "/").lower()
        if fp and fp not in by_file:
            by_file[fp] = d0
        t = str(d0.get("title") or "").strip().lower()
        if t and t not in by_title:
            by_title[t] = d0
    out: List[Dict[str, Any]] = []
    for f in kept or []:
        d = _as_d(f)
        src = by_file.get(str(d.get("file") or "").replace("\\", "/").lower())
        if src is None:
            src = by_title.get(str(d.get("title") or "").strip().lower())
        if src:
            for k in _STAMP_KEYS:
                if k in src:
                    d[k] = src[k]
        out.append(d)
    return out


def _slice_failed(sl: Dict[str, Any] | None) -> bool:
    if not sl:
        return False
    if sl.get("skipped"):
        return False
    if (sl.get("failed") or 0) > 0:
        return True
    return sl.get("exit_code") not in (None, 0)


def _execution_failed(execution: Dict[str, Any] | None) -> bool:
    ex = execution or {}
    if _slice_failed(ex.get("python") if isinstance(ex.get("python"), dict) else None):
        return True
    if _slice_failed(ex.get("js") if isinstance(ex.get("js"), dict) else None):
        return True
    if ex.get("skipped"):
        return False
    if (ex.get("failed") or 0) > 0:
        return True
    code = ex.get("exit_code")
    return code not in (None, 0)


def recommendation_from_verification(
    findings: List[Dict[str, Any]] | None,
    *,
    classification: str = "",
    risk: str = "medium",
    execution: Dict[str, Any] | None = None,
) -> str:
    """REQUEST_CHANGES only for supported findings with severity >= medium.

    unsupported cannot be the sole reason for REQUEST_CHANGES.
    lockfile-only never REQUEST_CHANGES from hunk tokens alone (COMMENT).
    Failed pytest (4.3) on a source PR can REQUEST_CHANGES even if the
    finding is only uncertain / a testing nit.
    """
    findings = list(findings or [])
    if classification != "lockfile-only" and (
        _execution_failed(execution)
        or any(f.get("tests_passed") is False for f in findings)
    ):
        return "REQUEST_CHANGES"
    supported = [f for f in findings if f.get("verification_status") == "supported"]
    uncertain = [f for f in findings if f.get("verification_status") == "uncertain"]
    blocking = [
        f
        for f in supported
        if str(f.get("severity") or "").lower() in MEDIUM_PLUS
    ]
    if blocking:
        if classification == "lockfile-only":
            return "COMMENT"
        return "REQUEST_CHANGES"
    if supported or uncertain:
        return "COMMENT"
    if classification == "lockfile-only":
        return "COMMENT"
    if str(risk).lower() in ("medium", "high", "critical"):
        return "COMMENT"
    return "MERGE"
