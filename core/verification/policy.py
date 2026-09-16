"""How critic/final treat verification grades. Pure function — unit-tested."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from core.agent.contract import (
    as_finding_kind,
    is_changelog_title,
    is_hedge,
    is_test_name_restatement,
)
from core.pr_facts import is_source_file

COVERAGE_MERGE_MIN = 0.5

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


def _merge_min(explicit: Optional[float]) -> float:
    if explicit is not None:
        try:
            return float(explicit)
        except (TypeError, ValueError):
            pass
    try:
        from config import settings

        return float(getattr(settings, "coverage_merge_min", COVERAGE_MERGE_MIN) or COVERAGE_MERGE_MIN)
    except Exception:
        return COVERAGE_MERGE_MIN


def coverage_score(
    review_coverage: Optional[Dict[str, Any]],
    *,
    classification: str = "",
    files_changed: Optional[List[str]] = None,
    coverage_merge_min: Optional[float] = None,
) -> Tuple[float, bool]:
    """Deterministic pack ratio. Low := ratio < min, or source units packed none.

    Missing coverage dict is not scored here — callers pass known=False to decide().
    """
    cov = review_coverage if isinstance(review_coverage, dict) else {}
    total = int(cov.get("units_total") or 0)
    packed = int(cov.get("units_packed") or 0)
    source_units = int(cov.get("source_units") or 0)
    files = list(files_changed or [])
    has_source = any(is_source_file(p) for p in files)
    lockfile_only = classification == "lockfile-only"
    threshold = _merge_min(coverage_merge_min)

    if total == 0:
        if has_source:
            ratio = 0.0
        elif lockfile_only:
            ratio = 1.0
        elif files:
            ratio = 0.0
        else:
            ratio = 1.0
    elif source_units == 0 and lockfile_only:
        ratio = 1.0
    else:
        ratio = packed / total if total else 0.0

    low = ratio < threshold
    if source_units > 0 and packed == 0:
        low = True
    return ratio, low


def _confidence(finding: Dict[str, Any]) -> Optional[float]:
    if "confidence" not in finding:
        return None
    try:
        return float(finding.get("confidence"))
    except (TypeError, ValueError):
        return None


def _cap_changelog_severity(finding: Dict[str, Any]) -> Dict[str, Any]:
    f = dict(finding or {})
    title = str(f.get("title") or "")
    claim = str(f.get("claim") or f.get("description") or "")
    if is_changelog_title(title) or is_test_name_restatement(title, claim):
        if str(f.get("severity") or "").lower() in MEDIUM_PLUS:
            f["severity"] = "nit"
        f["kind"] = "note"
    return f


def _cap_hedge(finding: Dict[str, Any]) -> Dict[str, Any]:
    f = dict(finding or {})
    title = str(f.get("title") or "")
    claim = str(f.get("claim") or f.get("description") or "")
    if is_hedge(title, claim, _confidence(f)):
        f["severity"] = "nit"
        f["verify_status"] = "uncertain"
    return f


def _is_blocking_defect(finding: Dict[str, Any] | None) -> bool:
    return as_finding_kind(finding or {}) == "defect"


def _verify_status(finding: Dict[str, Any]) -> str:
    vs = str(finding.get("verify_status") or "").strip().lower()
    if vs in ("verified", "disproved", "uncertain", "candidate"):
        return vs
    vstat = str(finding.get("verification_status") or "").lower()
    if vstat == "uncertain":
        return "uncertain"
    if vstat == "supported":
        return "verified"
    return "candidate"


def decide(
    findings: List[Dict[str, Any]] | None,
    *,
    classification: str = "",
    coverage: Optional[Dict[str, Any]] = None,
    suggested_from_4_1: Optional[str] = None,
    risk: str = "medium",
    execution: Dict[str, Any] | None = None,
    files_changed: Optional[List[str]] = None,
    coverage_merge_min: Optional[float] = None,
) -> Tuple[str, str]:
    """RC only on verified medium+ defects. Coverage is observational."""
    _ = suggested_from_4_1, coverage, risk, files_changed, coverage_merge_min
    findings = list(findings or [])
    if classification == "lockfile-only":
        return "COMMENT", "lockfile-only"

    if _execution_failed(execution) or any(f.get("tests_passed") is False for f in findings):
        return "REQUEST_CHANGES", "tests_failed"

    findings = [_cap_changelog_severity(f) for f in findings]
    findings = [_cap_hedge(f) for f in findings]
    findings = [f for f in findings if as_finding_kind(f) != "note"]
    findings = [f for f in findings if _verify_status(f) == "verified"]

    verified_block = [
        f
        for f in findings
        if str(f.get("severity") or "").lower() in MEDIUM_PLUS
        and _is_blocking_defect(f)
    ]
    if verified_block:
        return "REQUEST_CHANGES", "verified_medium"

    if findings:
        return "COMMENT", "verified_nit"
    return "MERGE", "no_findings"


def recommendation_from_verification(
    findings: List[Dict[str, Any]] | None,
    *,
    classification: str = "",
    risk: str = "medium",
    execution: Dict[str, Any] | None = None,
    coverage: Optional[Dict[str, Any]] = None,
    files_changed: Optional[List[str]] = None,
    coverage_merge_min: Optional[float] = None,
) -> str:
    """REQUEST_CHANGES only for supported findings with severity >= medium.

    unsupported cannot be the sole reason for REQUEST_CHANGES.
    lockfile-only never REQUEST_CHANGES from hunk tokens alone (COMMENT).
    Failed pytest (4.3) on a source PR can REQUEST_CHANGES even if the
    finding is only uncertain / a testing nit.
    Coverage (7.3): empty KEEP + low pack ratio cannot MERGE.
    """
    rec, _reason = decide(
        findings,
        classification=classification,
        coverage=coverage,
        risk=risk,
        execution=execution,
        files_changed=files_changed,
        coverage_merge_min=coverage_merge_min,
    )
    return rec


def policy_from_state(
    state: dict,
    findings: List[Dict[str, Any]] | None = None,
    *,
    execution: Dict[str, Any] | None = None,
) -> Tuple[str, str, float, bool]:
    """Decide from review state. Logs [Coverage] when review_coverage is present."""
    state = state or {}
    facts = state.get("pr_facts") if isinstance(state.get("pr_facts"), dict) else {}
    classification = str(facts.get("classification") or "")
    files = list(facts.get("files_changed") or state.get("files_changed") or [])
    understanding = state.get("pr_understanding") or {}
    risk = ""
    if isinstance(understanding, dict):
        risk = str(understanding.get("risk_level") or "")
    plan = state.get("review_plan") or {}
    if isinstance(plan, dict) and plan.get("risk_level"):
        risk = str(plan.get("risk_level") or risk)
    cov = state.get("review_coverage")
    coverage = cov if isinstance(cov, dict) else None
    merge_min = state.get("coverage_merge_min")
    if findings is None:
        findings = list(state.get("validated_findings") or state.get("findings") or [])
    if execution is None:
        ex = state.get("execution_report")
        execution = ex if isinstance(ex, dict) else None
    rec, reason = decide(
        findings,
        classification=classification,
        coverage=coverage,
        risk=risk or "medium",
        execution=execution,
        files_changed=files,
        coverage_merge_min=merge_min if merge_min is not None else None,
    )
    ratio, low = 1.0, False
    if coverage is not None:
        ratio, low = coverage_score(
            coverage,
            classification=classification,
            files_changed=files,
            coverage_merge_min=merge_min if merge_min is not None else None,
        )
        packed = int(coverage.get("units_packed") or 0)
        total = int(coverage.get("units_total") or 0)
        print(
            f"[Coverage] packed={packed} total={total} ratio={ratio:.2f} "
            f"low={str(low).lower()} (observational)"
        )
    return rec, reason, ratio, low


_REC_RANK = {"MERGE": 0, "COMMENT": 1, "REQUEST_CHANGES": 2}


def clamp_recommendation(
    rec: str,
    baseline: str,
    classification: str = "",
    policy_reason: str = "",
) -> str:
    """Policy owns MERGE / COMMENT / REQUEST_CHANGES. LLM text cannot change it.

    Lockfile-only cannot MERGE or REQUEST_CHANGES.
    Low coverage never MERGE (LLM cannot override insufficient_coverage).
    """
    _ = rec
    base = str(baseline or "COMMENT").upper()
    if base not in _REC_RANK:
        base = "COMMENT"
    rec = base
    if policy_reason == "insufficient_coverage" and rec == "MERGE":
        rec = "COMMENT"
    if classification == "lockfile-only" and rec in ("MERGE", "REQUEST_CHANGES"):
        return "COMMENT"
    return rec
