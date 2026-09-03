"""Gate scorer. Pass/fail only — no BLEU, no comment quality."""

from __future__ import annotations

import re
from typing import List, Optional

from core.pr_facts import is_source_file, normalize_path
from core.verification.policy import MEDIUM_PLUS
from tests.evaluation.schema import CheckResult, GoldenCase, Scorecard
from core.evaluation.snapshot import ReviewSnapshot

TRIVIA_BASENAMES = {
    "wordlist.txt",
    ".gitignore",
    "license",
    "makefile",
    ".dockerignore",
}


def _norm(p: str) -> str:
    return normalize_path(str(p or ""))


def _base(p: str) -> str:
    return _norm(p).split("/")[-1].lower()


def _in_set(path: str, allowed: List[str]) -> bool:
    n = _norm(path).lower()
    b = _base(path)
    for a in allowed:
        an = _norm(a).lower()
        if n == an or b == an.split("/")[-1]:
            return True
    return False


def _chk(name: str, ok: bool, detail: str = "") -> CheckResult:
    return CheckResult(name=name, passed=bool(ok), detail=detail)


def _execute_expect(golden: GoldenCase, profile: str) -> str:
    if profile == "execute" and golden.execute_even_with_flags:
        return golden.execute_even_with_flags
    if profile == "execute" and not golden.lockfile_only:
        return "any"
    return golden.execute_default


def score(
    golden: GoldenCase,
    snap: ReviewSnapshot,
    *,
    profile: str = "gates",
) -> Scorecard:
    checks: List[CheckResult] = []

    checks.append(
        _chk(
            "classification",
            snap.classification == golden.classification,
            f"expected {golden.classification} got {snap.classification}",
        )
    )

    changed = {_norm(p).lower() for p in snap.files_changed}
    missing = [
        p
        for p in golden.must_include_files
        if _norm(p).lower() not in changed
        and _base(p) not in {_base(c) for c in snap.files_changed}
    ]
    checks.append(
        _chk(
            "must_include_files",
            not missing,
            f"missing {missing} in files_changed",
        )
    )

    if golden.investigate == "skip":
        reason = snap.skip_reason or ""
        matched = True
        if golden.skip_reason_contains:
            matched = bool(re.search(golden.skip_reason_contains, reason, re.I))
        checks.append(
            _chk(
                "investigate",
                bool(snap.investigate_skipped) and matched,
                f"skipped={snap.investigate_skipped} reason={reason!r}",
            )
        )
        checks.append(
            _chk("hops", True, "skip — hop jail not required")
        )
    else:
        over = snap.calls > int(golden.max_investigate_calls)
        checks.append(
            _chk(
                "investigate",
                (not snap.investigate_skipped) and not over,
                f"skipped={snap.investigate_skipped} calls={snap.calls} "
                f"max={golden.max_investigate_calls}",
            )
        )
        source_changed = {
            _norm(p).lower()
            for p in (snap.source_files or snap.files_changed)
            if is_source_file(p)
        }
        if not source_changed:
            source_changed = {_norm(p).lower() for p in snap.files_changed if is_source_file(p)}
        bad = []
        for hf in snap.hyp_files:
            n = _norm(hf)
            if not n:
                continue
            if _base(n) in TRIVIA_BASENAMES:
                bad.append(n)
                continue
            if is_source_file(n) and n.lower() not in source_changed:
                bad.append(n)
        checks.append(
            _chk("hops", not bad, f"hyp files outside source files_changed or trivia: {bad}")
        )

    trivia_kept = [p for p in snap.keep_files if _base(p) in TRIVIA_BASENAMES]
    checks.append(
        _chk(
            "keep_paths",
            not (golden.trivia_keep_forbidden and trivia_kept),
            f"trivia KEEP {trivia_kept}",
        )
    )

    if golden.keep_files_allowed is not None:
        extra = [p for p in snap.keep_files if not _in_set(p, golden.keep_files_allowed)]
        checks.append(
            _chk(
                "keep_files_allowed",
                not extra,
                f"KEEP outside allowed {golden.keep_files_allowed}: {extra}",
            )
        )

    if snap.keep_files or snap.grounding_kept:
        statuses = list(snap.keep_verification_status or [])
        n = max(len(snap.keep_files), int(snap.grounding_kept or 0))
        if len(statuses) < n:
            statuses = statuses + [""] * (n - len(statuses))
        missing_st = [
            snap.keep_files[i] if i < len(snap.keep_files) else f"keep[{i}]"
            for i, st in enumerate(statuses[:n])
            if st not in ("supported", "uncertain", "unsupported")
        ]
        # If we have keep files but no status list (log parse), require verify_* counts
        if not snap.keep_verification_status and (
            snap.verify_supported + snap.verify_uncertain + snap.verify_unsupported
        ) >= max(1, len(snap.keep_files)):
            missing_st = []
        checks.append(
            _chk(
                "verify",
                not missing_st,
                f"KEEP missing verification_status: {missing_st}",
            )
        )
    else:
        checks.append(_chk("verify", True, "no KEEP findings"))

    if golden.tests_touched_max is not None:
        checks.append(
            _chk(
                "tests_touched_max",
                snap.tests_touched_count <= golden.tests_touched_max,
                f"tests_touched={snap.tests_touched_count} max={golden.tests_touched_max}",
            )
        )

    expect_ex = _execute_expect(golden, profile)
    reason = (snap.execute_skip_reason or "").lower()
    if expect_ex == "any":
        ex_ok = True
        detail = f"skipped={snap.execute_skipped} reason={snap.execute_skip_reason}"
    elif expect_ex == "skip_disabled":
        ex_ok = bool(snap.execute_skipped) and (
            "disabled" in reason or not reason
        )
        detail = f"expected skip_disabled got skipped={snap.execute_skipped} reason={snap.execute_skip_reason}"
    elif expect_ex == "skip_lockfile-only":
        ex_ok = bool(snap.execute_skipped) and "lockfile-only" in reason
        detail = f"expected skip_lockfile-only got skipped={snap.execute_skipped} reason={snap.execute_skip_reason}"
    else:
        ex_ok = True
        detail = ""
    checks.append(_chk("execute_default", ex_ok, detail))

    dec = str(snap.final_decision or "").upper()
    allowed = [str(x).upper() for x in golden.final_allowed]
    checks.append(
        _chk("final", dec in allowed, f"expected {allowed} got {dec}")
    )

    if golden.forbid_request_changes_unless_supported_medium and dec == "REQUEST_CHANGES":
        has_supported_medium = False
        for st, sev in zip(snap.keep_verification_status, snap.keep_severity):
            if st == "supported" and str(sev).lower() in MEDIUM_PLUS:
                has_supported_medium = True
                break
        if not snap.keep_verification_status:
            has_supported_medium = snap.verify_supported >= 1
        clamp_ok = snap.verify_supported >= 1 and (
            has_supported_medium or not snap.keep_severity
        )
        checks.append(
            _chk(
                "clamp",
                clamp_ok,
                f"REQUEST_CHANGES with supported={snap.verify_supported} "
                f"statuses={snap.keep_verification_status} sevs={snap.keep_severity}",
            )
        )
    else:
        checks.append(_chk("clamp", True, "N/A"))

    checks.append(
        _chk(
            "qdrant",
            bool(snap.qdrant_used) == bool(golden.qdrant),
            f"qdrant_used={snap.qdrant_used} expected={golden.qdrant}",
        )
    )

    return Scorecard(case_id=golden.id, checks=checks)
