"""Falsify defect candidates before Policy. Coverage never decides."""

from __future__ import annotations

import re
from typing import Any, Callable, List, Optional, Sequence, Tuple

from core.agent.contract import is_hedge, proof_complete
from core.graphctx.symbols import is_valid_symbol
from core.pr_facts import normalize_path
from core.runtime.models import Bundle, Candidate
from core.runtime.qualify import (
    NOT_A_DEFECT,
    PLAUSIBLE_BUT_UNPROVEN,
    qualify_finding,
)
from core.verification.diff_index import DiffIndex

MAX_VERIFY = 3
MAX_GRAPHIFY = 4
_STATUS_RE = re.compile(r"\b(DISPROVED|VERIFIED|UNCERTAIN)\b", re.I)
_GUARD_TOKS = ("raise", "validate", "if trial.job_id", "job_id")
_ENFORCE_RE = re.compile(
    r"(?i)(\braise\b|\bValueError\b|\bTypeError\b|\bAssertionError\b|"
    r"console\.print\(\s*[\"']Error|[\"']Error:|\bassert\b)"
)
_INV_STOP = {
    "that",
    "this",
    "with",
    "from",
    "should",
    "must",
    "when",
    "where",
    "case",
    "function",
    "provided",
    "handle",
    "handling",
    "missing",
    "error",
    "exactly",
    "into",
    "have",
    "been",
    "will",
    "would",
    "the",
    "and",
    "for",
    "not",
    "only",
    "than",
    "then",
    "does",
    "already",
}

_FALSIFY_SYS = (
    "You only try to DISPROVE the claim. Cite code. "
    "Ask: where is the violation? Not: is this concern plausible. "
    "If the snippet is a guard that already enforces the invariant "
    "(raise, Error print, assert), say DISPROVED. "
    "If you cannot show a violating execution path to an observable "
    "consequence, say UNCERTAIN. "
    "If the path is real, unguarded, and the consequence is observable, "
    "say VERIFIED. "
    "Do not invent files."
)


def _hunk_text(index: Optional[DiffIndex], path: str) -> str:
    if index is None:
        return ""
    parts = []
    for h in index.hunks_for(path):
        parts.append(h.added or "")
        parts.append(h.body or "")
    return "\n".join(parts)


def _snippet_in_hunk(snippet: str, hunk: str) -> bool:
    s = " ".join((snippet or "").split())
    h = " ".join((hunk or "").split())
    if not s or not h:
        return False
    if s in h:
        return True
    # tolerate +/- prefixes stripped
    s2 = s.lstrip("+-").strip()
    return bool(s2) and s2 in h


def _inv_tokens(text: str) -> List[str]:
    out: List[str] = []
    seen = set()
    for tok in re.findall(r"[A-Za-z_][A-Za-z0-9_]{3,}", text or ""):
        low = tok.lower()
        if low in _INV_STOP or low in seen:
            continue
        seen.add(low)
        out.append(low)
    return out


def snippet_enforces_invariant(cand: Candidate, hunk: str = "") -> bool:
    """True when existing_code is the guard that already enforces the invariant."""
    _ = hunk
    blob = cand.existing_code or ""
    if not blob or not _ENFORCE_RE.search(blob):
        return False
    inv = f"{cand.invariant or ''} {cand.claim or ''} {cand.title or ''}"
    low = blob.lower()
    hits = 0
    for t in _inv_tokens(inv):
        if t in low or (t.endswith("s") and t[:-1] in low):
            hits += 1
    return hits >= 1


def _last_symbol(path: Sequence[str]) -> str:
    for item in reversed(list(path or [])):
        s = str(item or "").strip()
        if s:
            return s
    return ""


def _graph_disproves(client: Any, symbol: str, invariant: str, budget: list) -> Tuple[bool, str]:
    if client is None or not symbol or budget[0] >= MAX_GRAPHIFY:
        return False, ""
    label = symbol.split(".")[-1] if "." in symbol else symbol
    text = ""
    try:
        node = client.get_node(label)
        budget[0] += 1
        if node is not None:
            text += str(getattr(node, "raw_text", None) or getattr(node, "raw", {}) or "")
            if isinstance(getattr(node, "raw", None), dict):
                text += str(node.raw.get("text") or "")
        if budget[0] < MAX_GRAPHIFY:
            neigh = client.get_neighbors(label)
            budget[0] += 1
            text += str(getattr(neigh, "raw_text", None) or "")
    except Exception:
        return False, ""
    blob = text.lower()
    inv = (invariant or "").lower()
    if not blob:
        return False, ""
    if any(g in blob for g in _GUARD_TOKS) and any(
        tok for tok in inv.split() if len(tok) >= 4 and tok in blob
    ):
        return True, text[:400]
    if "raise" in blob and ("validate" in blob or "job_id" in blob):
        return True, text[:400]
    return False, ""


def _bundle_for(cand: Candidate, bundles: Sequence[Bundle]) -> Optional[Bundle]:
    file = normalize_path(cand.file)
    for b in bundles or []:
        if file in [normalize_path(p) for p in b.paths]:
            return b
    return None


def _test_covers_invariant(cand: Candidate, bundle: Optional[Bundle]) -> bool:
    if bundle is None:
        return False
    inv = (cand.invariant or "").lower()
    tokens = [t for t in re.findall(r"[a-zA-Z_][a-zA-Z0-9_]{3,}", inv)]
    if not tokens:
        return False
    for u in bundle.units or []:
        path = normalize_path(u.get("path") if isinstance(u, dict) else getattr(u, "path", ""))
        base = path.split("/")[-1].lower()
        excerpt = str(u.get("excerpt") if isinstance(u, dict) else getattr(u, "excerpt", "") or "")
        blob = f"{base} {excerpt}".lower()
        if "test" not in base and "/tests/" not in f"/{path.lower()}/":
            continue
        hits = sum(1 for t in tokens if t.lower() in blob)
        if hits >= 1 and ("assert" in blob or "test" in base):
            return True
    return False


def _falsify_llm(cand: Candidate, llm: Optional[Callable[[str], str]], hunk: str) -> str:
    if llm is None:
        return "UNCERTAIN"
    prompt = (
        f"{_FALSIFY_SYS}\n"
        f"claim={cand.claim}\n"
        f"invariant={cand.invariant}\n"
        f"violating_condition={cand.violating_condition}\n"
        f"existing_code={cand.existing_code}\n"
        f"hunk:\n{hunk[:1500]}\n"
        "Answer with one of: DISPROVED VERIFIED UNCERTAIN"
    )
    try:
        raw = str(llm(prompt) or "")
    except Exception:
        return "UNCERTAIN"
    m = _STATUS_RE.search(raw)
    if not m:
        return "UNCERTAIN"
    return m.group(1).upper()


def _drop(cand: Candidate, reason: str, dropped: List[dict]) -> None:
    cand.verify_status = "disproved" if reason in ("disproved", "not_a_defect") else "uncertain"
    dropped.append({**cand.to_dict(), "drop_reason": reason})
    print(f"[Verify] DROP reason={reason} file={cand.file} title={cand.title!r}")


def verify_candidates(
    candidates: Sequence[Candidate],
    *,
    index: Optional[DiffIndex] = None,
    bundles: Optional[Sequence[Bundle]] = None,
    client: Any = None,
    llm: Optional[Callable[[str], str]] = None,
) -> Tuple[List[Candidate], List[dict]]:
    """Return (verified survivors, dropped). Uncertain is not a comment."""
    kept: List[Candidate] = []
    dropped: List[dict] = []
    graph_budget = [0]
    verified_n = 0
    for cand in candidates:
        if str(getattr(cand, "kind", "defect") or "defect").lower() != "defect":
            _drop(cand, "note", dropped)
            continue
        if not proof_complete(cand.to_dict()):
            _drop(cand, "incomplete_proof", dropped)
            continue
        if verified_n >= MAX_VERIFY:
            _drop(cand, "unproven", dropped)
            continue
        if is_hedge(cand.title, cand.claim, getattr(cand, "confidence", None)):
            cand.severity = "nit"
            _drop(cand, "unproven", dropped)
            continue
        hunk = _hunk_text(index, cand.file)
        if not _snippet_in_hunk(cand.existing_code, hunk):
            _drop(cand, "snippet_not_in_hunk", dropped)
            continue
        q = qualify_finding(cand, hunk)
        if q.status == NOT_A_DEFECT:
            _drop(cand, "not_a_defect", dropped)
            continue
        if q.status == PLAUSIBLE_BUT_UNPROVEN and q.reason != "plausible":
            _drop(cand, q.reason or "unproven", dropped)
            continue
        if snippet_enforces_invariant(cand, hunk):
            _drop(cand, "not_a_defect", dropped)
            continue
        if not (cand.execution_path or cand.symbol):
            _drop(cand, "no_execution_path", dropped)
            continue
        bad_sym = False
        for s in cand.execution_path or []:
            if not is_valid_symbol(str(s)):
                _drop(cand, "symbol_is_path", dropped)
                bad_sym = True
                break
        if bad_sym:
            continue
        last = _last_symbol(cand.execution_path) or cand.symbol
        disproved, counter = _graph_disproves(client, last, cand.invariant, graph_budget)
        if disproved:
            if counter:
                cand.counter_evidence = list(cand.counter_evidence or []) + [counter]
            _drop(cand, "disproved", dropped)
            continue
        bundle = _bundle_for(cand, bundles or [])
        if _test_covers_invariant(cand, bundle):
            claim = f"{cand.title} {cand.claim}".lower()
            if "test does not cover" not in claim:
                cand.counter_evidence = list(cand.counter_evidence or []) + [
                    "same-bundle test asserts invariant"
                ]
                _drop(cand, "disproved", dropped)
                continue
        status = _falsify_llm(cand, llm, hunk)
        if status == "DISPROVED":
            _drop(cand, "disproved", dropped)
            continue
        if status != "VERIFIED":
            _drop(cand, "unproven", dropped)
            continue
        if snippet_enforces_invariant(cand, hunk):
            _drop(cand, "not_a_defect", dropped)
            continue
        q2 = qualify_finding(cand, hunk)
        if q2.status == NOT_A_DEFECT or (
            q2.status == PLAUSIBLE_BUT_UNPROVEN and q2.reason != "plausible"
        ):
            _drop(cand, q2.reason or "unproven", dropped)
            continue
        cand.verify_status = "verified"
        kept.append(cand)
        verified_n += 1
    return kept, dropped
