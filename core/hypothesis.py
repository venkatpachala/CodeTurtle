"""Internal hypothesis statuses. GitHub still posts KEEP only."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

from core.finding_validator import (
    _as_dict,
    _is_trivial,
    _path_in_allowed,
    _text,
    normalize_findings,
    validate_finding,
)
from core.pr_facts import extract_diff_symbols, normalize_path
from core.verification.diff_index import build_diff_index
from core.verification.hunk_verifier import MIN_TOKEN_HITS, claim_tokens

KEEP = "KEEP"
PLAUSIBLE = "PLAUSIBLE"
REJECTED = "REJECTED"
UNRESOLVED = "UNRESOLVED"
HypothesisStatus = str  # KEEP | PLAUSIBLE | REJECTED | UNRESOLVED
POSTABLE_STATUSES = frozenset({KEEP})

_FAKE_RE = re.compile(r"\bFake(?:Cursor|Connection|Client|Repo|PR|Test)\b", re.I)
_EMPTY_EXACT = frozenset(
    {
        "no issues",
        "no findings",
        "no problems",
        "none",
        "n/a",
        "lgtm",
        "looks good",
        "ok",
        "okay",
        "looks good to me",
    }
)
_EMPTY_PREFIXES = (
    "no issues",
    "no findings",
    "no problems",
    "no blocking",
)


def _word_in(hay: str, needle: str) -> bool:
    n = (needle or "").strip()
    if not n or not hay:
        return False
    try:
        return bool(re.search(r"(?<![A-Za-z0-9_])" + re.escape(n) + r"(?![A-Za-z0-9_])", hay))
    except re.error:
        return n.lower() in hay.lower()


def _basename_in_text(text: str, files_changed: List[str]) -> Optional[str]:
    blob = (text or "").replace("\\", "/")
    for p in files_changed or []:
        n = normalize_path(p)
        if not n or _is_trivial(n):
            continue
        base = n.split("/")[-1]
        if base and len(base) >= 4 and base in blob:
            return n
        if n in blob:
            return n
    return None


def classify_hypothesis(
    finding: Dict[str, Any],
    *,
    files_changed: List[str],
    full_diff: str = "",
    paths_in_diff: Optional[List[str]] = None,
    changed_symbols: Optional[List[str]] = None,
) -> Tuple[str, Dict[str, Any]]:
    """KEEP | PLAUSIBLE | REJECTED. Deterministic. No LLM."""
    f = finding if isinstance(finding, dict) else _as_dict(finding)
    extra: Dict[str, Any] = {}
    title = str(f.get("title") or "").strip()
    claim = str(f.get("claim") or f.get("description") or "").strip()
    if not title and not claim:
        return REJECTED, {"reason": "empty_claim"}
    blob = f"{title} {claim}".strip().lower().rstrip(".!")
    if blob in _EMPTY_EXACT or any(blob.startswith(p) for p in _EMPTY_PREFIXES):
        return REJECTED, {"reason": "empty_specialist"}
    if _FAKE_RE.search(title + " " + claim + " " + str(f.get("symbol") or "")):
        return REJECTED, {"reason": "invented_fake"}

    ok, reason = validate_finding(
        f,
        files_changed=files_changed,
        paths_in_diff=paths_in_diff,
        changed_symbols=changed_symbols or extract_diff_symbols(full_diff),
        full_diff=full_diff,
    )
    if ok:
        return KEEP, {"reason": "ok"}

    ev = f.get("evidence") or []
    if isinstance(ev, str):
        ev = [ev]
    ev_paths = [normalize_path(str(x)) for x in ev if x]
    fp = normalize_path(str(f.get("file") or ""))
    if fp:
        ev_paths.append(fp)
    trivia_only = bool(ev_paths) and all(_is_trivial(p) for p in ev_paths if p)

    index = build_diff_index(full_diff or "")
    tokens = claim_tokens(f)
    hunk_blob = ""
    for path in index.file_set():
        for h in index.hunks_for(path):
            hunk_blob += "\n" + (h.added or "") + "\n" + (h.removed or "")
    token_hits = [t for t in tokens if t.lower() in hunk_blob.lower()]
    distinctive = [t for t in token_hits if t.startswith("@")]
    tokens_in_hunk = bool(distinctive) or len(token_hits) >= MIN_TOKEN_HITS
    tokens_in_diff = any(t.lower() in (full_diff or "").lower() for t in tokens)

    if trivia_only and not tokens_in_hunk and not tokens_in_diff:
        return REJECTED, {"reason": "trivia_only"}

    symbol = str(f.get("symbol") or "").strip()
    if symbol and _word_in(full_diff or "", symbol):
        hint = _basename_in_text(_text(f), files_changed) or _path_in_allowed(
            fp, files_changed
        )
        if hint:
            extra["file_hint"] = hint
        extra["reason"] = "symbol_in_diff"
        return PLAUSIBLE, extra

    if tokens_in_hunk:
        hint = _basename_in_text(_text(f), files_changed)
        if hint:
            extra["file_hint"] = hint
        extra["reason"] = "tokens_in_hunk"
        extra["matched_tokens"] = token_hits
        return PLAUSIBLE, extra

    if not fp:
        named = _basename_in_text(_text(f), files_changed)
        if named:
            extra["file_hint"] = named
            extra["reason"] = "named_changed_path"
            return PLAUSIBLE, extra

    named = _basename_in_text(_text(f), files_changed)
    if named:
        extra["file_hint"] = named
        extra["reason"] = "basename_in_claim"
        return PLAUSIBLE, extra

    return REJECTED, {"reason": reason or "ungrounded"}


def classify_findings(
    findings: List[Dict[str, Any]],
    *,
    files_changed: List[str],
    full_diff: str = "",
    paths_in_diff: Optional[List[str]] = None,
    changed_symbols: Optional[List[str]] = None,
) -> Tuple[List[dict], List[dict], List[dict]]:
    keep: List[dict] = []
    plausible: List[dict] = []
    rejected: List[dict] = []
    for f in findings or []:
        d = dict(f) if isinstance(f, dict) else _as_dict(f)
        status, extra = classify_hypothesis(
            d,
            files_changed=files_changed,
            full_diff=full_diff,
            paths_in_diff=paths_in_diff,
            changed_symbols=changed_symbols,
        )
        if not d.get("id"):
            d["id"] = f"hyp-{len(keep) + len(plausible) + len(rejected) + 1}"
        d["hypothesis_status"] = status
        if extra.get("file_hint"):
            d["file_hint"] = extra["file_hint"]
        if extra.get("matched_tokens"):
            d.setdefault("matched_tokens", extra["matched_tokens"])
        d["hypothesis_reason"] = extra.get("reason") or ""
        if status == KEEP:
            keep.append(d)
        elif status == PLAUSIBLE:
            plausible.append(d)
            print(
                f"[Hypotheses] PLAUSIBLE symbol={d.get('symbol') or ''} "
                f"file_hint={d.get('file_hint') or d.get('file') or ''}"
            )
        else:
            rejected.append(d)
    print(
        f"[Hypotheses] keep={len(keep)} plausible={len(plausible)} "
        f"rejected={len(rejected)}"
    )
    return keep, plausible, rejected


def classify_hypotheses_node(state: dict) -> dict:
    """LangGraph: specialists → classify → investigate. Cheap REJECTED filter."""
    from core.finding_validator import _category_bucket
    from core.pr_facts import allowed_paths as _allowed_paths_from_facts

    buckets = (
        ("correctness_findings", "correctness"),
        ("quality_findings", "code_quality"),
        ("testing_findings", "testing"),
    )
    facts = state.get("pr_facts") or {}
    files_changed = list(
        facts.get("files_changed") or state.get("files_changed") or []
    )
    raw_items: List[Dict[str, Any]] = []
    for key, cat in buckets:
        for item in list(state.get(key) or []):
            d = _as_dict(item)
            d["category"] = d.get("category") or cat
            raw_items.append(d)
    for item in list(state.get("failure_path_findings") or []):
        d = _as_dict(item)
        d["category"] = d.get("category") or "correctness"
        d["failure_path"] = True
        raw_items.append(d)
    if not raw_items:
        for item in list(state.get("findings") or state.get("validated_findings") or []):
            raw_items.append(_as_dict(item))

    normalized = normalize_findings(
        raw_items, files_changed=files_changed, pr_facts=facts
    )
    paths_in_diff = list(facts.get("paths_in_diff") or [])
    if not paths_in_diff and facts:
        paths_in_diff = list(_allowed_paths_from_facts(facts))
    full_diff = state.get("full_diff") or facts.get("full_diff") or ""
    changed_symbols = extract_diff_symbols(full_diff)
    keep, plausible, rejected = classify_findings(
        normalized,
        files_changed=files_changed,
        full_diff=full_diff,
        paths_in_diff=paths_in_diff,
        changed_symbols=changed_symbols,
    )
    classified = keep + plausible + rejected
    pool = keep + plausible
    by_cat = {"correctness": [], "code_quality": [], "testing": []}
    for f in keep:
        bucket = _category_bucket(str(f.get("category") or ""))
        if bucket in by_cat:
            by_cat[bucket].append(f)
        else:
            by_cat["correctness"].append(f)
    report = {
        "keep": len(keep),
        "plausible": len(plausible),
        "rejected": len(rejected),
    }
    return {
        "classified_findings": classified,
        "hypothesis_pool": pool,
        "validated_findings": keep,
        "findings": keep,
        "hypothesis_report": report,
        "correctness_findings": by_cat["correctness"],
        "quality_findings": by_cat["code_quality"],
        "testing_findings": by_cat["testing"],
        "traces": [
            {
                "agent": "HypothesisClassifier",
                "output": (
                    f"keep={len(keep)} plausible={len(plausible)} "
                    f"rejected={len(rejected)}"
                ),
            }
        ],
    }


def is_keep_for_post(finding: Dict[str, Any] | None) -> bool:
    """GitHub / critic / 4.1: KEEP only. Missing status is KEEP (legacy)."""
    d = finding or {}
    st = str(d.get("hypothesis_status") or KEEP)
    return st in POSTABLE_STATUSES
