"""Falsify defect candidates before Policy. Coverage never decides."""

from __future__ import annotations

import re
from typing import Any, Callable, List, Optional, Sequence, Tuple

from core.agent.contract import is_hedge, proof_complete
from core.graphctx.symbols import is_valid_symbol
from core.pr_facts import normalize_path
from core.runtime.models import Bundle, Candidate
from core.verification.diff_index import DiffIndex

MAX_VERIFY = 3
MAX_GRAPHIFY = 4
_STATUS_RE = re.compile(r"\b(DISPROVED|VERIFIED|UNCERTAIN)\b", re.I)
_GUARD_TOKS = ("raise", "validate", "if trial.job_id", "job_id")

_FALSIFY_SYS = (
    "You only try to DISPROVE the claim. Cite code. "
    "If you find validation/test/contract that prevents the bug, say DISPROVED. "
    "If the path is real and unguarded, say VERIFIED. "
    "If you cannot tell, UNCERTAIN. "
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


def verify_candidates(
    candidates: Sequence[Candidate],
    *,
    index: Optional[DiffIndex] = None,
    bundles: Optional[Sequence[Bundle]] = None,
    client: Any = None,
    llm: Optional[Callable[[str], str]] = None,
) -> Tuple[List[Candidate], List[dict]]:
    """Return (survivors, dropped). Max 3 defects, ≤1 LLM falsify each."""
    kept: List[Candidate] = []
    dropped: List[dict] = []
    graph_budget = [0]
    verified_n = 0
    for cand in candidates:
        if str(getattr(cand, "kind", "defect") or "defect").lower() != "defect":
            dropped.append({**cand.to_dict(), "drop_reason": "note"})
            continue
        if not proof_complete(cand.to_dict()):
            dropped.append({**cand.to_dict(), "drop_reason": "incomplete_proof"})
            print(f"[Verify] DROP reason=incomplete_proof file={cand.file}")
            continue
        if verified_n >= MAX_VERIFY:
            cand.verify_status = "uncertain"
            kept.append(cand)
            continue
        if is_hedge(cand.title, cand.claim, getattr(cand, "confidence", None)):
            cand.severity = "nit"
            cand.verify_status = "uncertain"
            kept.append(cand)
            verified_n += 1
            continue
        hunk = _hunk_text(index, cand.file)
        if not _snippet_in_hunk(cand.existing_code, hunk):
            dropped.append({**cand.to_dict(), "drop_reason": "snippet_not_in_hunk"})
            print(f"[Verify] DROP reason=snippet_not_in_hunk file={cand.file}")
            continue
        bad_sym = False
        for s in cand.execution_path or []:
            if not is_valid_symbol(str(s)):
                dropped.append({**cand.to_dict(), "drop_reason": "symbol_is_path"})
                bad_sym = True
                break
        if bad_sym:
            continue
        last = _last_symbol(cand.execution_path) or cand.symbol
        disproved, counter = _graph_disproves(client, last, cand.invariant, graph_budget)
        if disproved:
            cand.verify_status = "disproved"
            if counter:
                cand.counter_evidence = list(cand.counter_evidence or []) + [counter]
            dropped.append({**cand.to_dict(), "drop_reason": "disproved"})
            print(f"[Verify] DROP reason=disproved file={cand.file} title={cand.title!r}")
            continue
        bundle = _bundle_for(cand, bundles or [])
        if _test_covers_invariant(cand, bundle):
            claim = f"{cand.title} {cand.claim}".lower()
            if "test does not cover" not in claim:
                cand.verify_status = "uncertain"
                cand.counter_evidence = list(cand.counter_evidence or []) + [
                    "same-bundle test asserts invariant"
                ]
                kept.append(cand)
                verified_n += 1
                continue
        status = _falsify_llm(cand, llm, hunk)
        if status == "DISPROVED":
            cand.verify_status = "disproved"
            dropped.append({**cand.to_dict(), "drop_reason": "disproved"})
            print(f"[Verify] DROP reason=disproved file={cand.file} title={cand.title!r}")
            continue
        if status == "VERIFIED":
            cand.verify_status = "verified"
        else:
            cand.verify_status = "uncertain"
        kept.append(cand)
        verified_n += 1
    return kept, dropped
