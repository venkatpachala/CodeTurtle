"""Deterministic finding normalizer + validator. No LLM.

Pipeline: normalize → L1–L5 validate → KEEP/DROP logs → kept list.
The same kept list is what critic, Final, and display must use.
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, Iterable, List, Optional, Tuple

from core.pr_facts import (
    allowed_paths as _allowed_paths_from_facts,
    extract_diff_symbols,
    normalize_path,
)

LOCKFILE_CLAIM_TOKENS = (
    "lockfile",
    "package-lock",
    "yarn.lock",
    "pnpm-lock",
    "cargo.lock",
    "poetry.lock",
    "dependency",
    "dependencies",
    "version",
    "npm",
    "yarn",
    "pnpm",
    "compat",
    "@",
)

TRIVIAL_PATHS = (
    ".gitignore",
    "LICENSE",
    "Makefile",
    ".dockerignore",
    "wordlist.txt",
)

CODE_EXTS = (
    ".py",
    ".ts",
    ".tsx",
    ".js",
    ".jsx",
    ".go",
    ".rs",
    ".java",
    ".kt",
    ".cs",
    ".cpp",
    ".c",
    ".rb",
    ".php",
    ".swift",
)

_SYMBOL_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_.]*$")


def _norm(p: str) -> str:
    return normalize_path(p)


# ── Normalizer ───────────────────────────────────────────────────────────────

def _as_dict(finding: Any) -> Dict[str, Any]:
    """Flatten pydantic / dict / JSON string / object into a plain dict."""
    if finding is None:
        return {}
    if isinstance(finding, str):
        text = finding.strip()
        if not text:
            return {}
        if text[0] in "{[":
            try:
                parsed = json.loads(text)
            except Exception:
                return {"title": text}
            if isinstance(parsed, dict):
                finding = parsed
            elif isinstance(parsed, list):
                return {}
            else:
                return {"title": text}
        else:
            return {"title": text}
    if isinstance(finding, dict):
        d = dict(finding)
    elif hasattr(finding, "model_dump"):
        d = finding.model_dump()
    elif hasattr(finding, "dict"):
        d = finding.dict()
    else:
        d = {
            "id": getattr(finding, "id", ""),
            "title": getattr(finding, "title", ""),
            "description": getattr(finding, "description", "")
            or getattr(finding, "detail", ""),
            "detail": getattr(finding, "detail", ""),
            "reasoning": getattr(finding, "reasoning", ""),
            "recommendation": getattr(finding, "recommendation", ""),
            "evidence": getattr(finding, "evidence", None)
            or getattr(finding, "evidence_paths", None)
            or [],
            "evidence_paths": getattr(finding, "evidence_paths", None) or [],
            "file": getattr(finding, "file", None),
            "path": getattr(finding, "path", None),
            "symbol": getattr(finding, "symbol", None),
            "claim": getattr(finding, "claim", ""),
            "severity": getattr(finding, "severity", ""),
            "confidence": getattr(finding, "confidence", 0.5),
            "category": getattr(finding, "category", ""),
            "start_line": getattr(finding, "start_line", None),
            "end_line": getattr(finding, "end_line", None),
            "needs_investigation": getattr(finding, "needs_investigation", False),
            "question": getattr(finding, "question", ""),
            "evidence_ids": getattr(finding, "evidence_ids", None) or [],
        }

    sev = d.get("severity")
    if hasattr(sev, "value"):
        d["severity"] = sev.value

    if not d.get("description"):
        d["description"] = d.get("detail") or d.get("reasoning") or ""
    if not d.get("reasoning"):
        d["reasoning"] = d.get("detail") or d.get("description") or ""
    if not d.get("claim"):
        d["claim"] = d.get("title") or ""

    ev = d.get("evidence")
    if not ev:
        ev = d.get("evidence_paths") or d.get("evidence_refs") or []
    d["evidence"] = _as_path_list(ev)
    return d


def _as_path_list(ev: Any) -> List[str]:
    if ev is None:
        return []
    if isinstance(ev, str):
        ev = [ev]
    out: List[str] = []
    for x in ev:
        s = _norm(str(x)) if x is not None else ""
        if s:
            out.append(s)
    return list(dict.fromkeys(out))


def _looks_like_symbol(s: str) -> bool:
    s = (s or "").strip()
    if not s or " " in s or len(s) > 80:
        return False
    return bool(_SYMBOL_RE.match(s))


def _is_empty_finding(d: Dict[str, Any]) -> bool:
    title = str(d.get("title") or "").strip()
    claim = str(d.get("claim") or "").strip()
    desc = str(d.get("description") or d.get("detail") or "").strip()
    if not title and not claim and not desc:
        return True
    low = title.lower()
    if low in ("looks good", "no issues", "none", "n/a", "no finding"):
        return True
    return False


def _flatten_raw(raw: Any) -> List[Any]:
    if raw is None:
        return []
    if isinstance(raw, str):
        text = raw.strip()
        if text.startswith("["):
            try:
                parsed = json.loads(text)
                if isinstance(parsed, list):
                    return parsed
            except Exception:
                return [raw]
        return [raw]
    if isinstance(raw, (list, tuple)):
        out: List[Any] = []
        for item in raw:
            if isinstance(item, list):
                out.extend(item)
            else:
                out.append(item)
        return out
    return [raw]


def _looks_like_dep_claim(blob_l: str) -> bool:
    return any(tok in blob_l for tok in LOCKFILE_CLAIM_TOKENS)


def _apply_repair(finding: dict, path: str) -> dict:
    finding["file"] = path
    finding["evidence"] = [path]
    finding["_path_repaired"] = True
    print(f"[Grounding] REPAIR file={path} title={finding.get('title') or ''}")
    return finding


def repair_finding_paths(
    finding: dict,
    files_changed: list[str],
    *,
    classification: str = "",
    lock_files: Optional[List[str]] = None,
) -> dict:
    """If the model discussed a changed file but left file/evidence empty, fill them.

    Never overwrites existing file/evidence — validator then decides (so wordlist
    citations still DROP). Recall patch for source-file PRs.
    Lockfile-only: dep/version claims may attach the lockfile path.
    """
    files = [f.replace("\\", "/") for f in files_changed or []]
    ev = finding.get("evidence") or []
    if isinstance(ev, str):
        ev = [ev]
    ev = [x for x in ev if x]
    file_ = (finding.get("file") or "").replace("\\", "/")

    if file_ or ev:
        return finding  # already pointed at something; validator decides

    blob = " ".join(
        [
            str(finding.get("title") or ""),
            str(finding.get("claim") or ""),
            str(finding.get("reasoning") or ""),
            str(finding.get("description") or ""),
            str(finding.get("detail") or ""),
        ]
    ).replace("\\", "/")
    blob_l = blob.lower()

    hits: List[str] = []
    for path in files:
        base = path.split("/")[-1]
        stem = base.rsplit(".", 1)[0]
        if (
            path.lower() in blob_l
            or (base and base.lower() in blob_l)
            or (len(stem) > 3 and stem.lower() in blob_l)
        ):
            hits.append(path)

    source = [h for h in hits if h.endswith((".py", ".ts", ".tsx", ".js", ".jsx"))]
    chosen = (source or hits)[:1]
    if chosen:
        return _apply_repair(finding, chosen[0])

    # Lockfile-only: attach the lockfile when the claim is about deps/versions.
    # Never when source files also changed (538 already has real paths).
    if classification == "lockfile-only" and _looks_like_dep_claim(blob_l):
        locks = [_norm(x) for x in (lock_files or []) if x]
        if not locks:
            locks = [p for p in files if p.split("/")[-1] in {
                "package-lock.json", "yarn.lock", "pnpm-lock.yaml",
                "Cargo.lock", "poetry.lock", "composer.lock",
            }]
        if 1 <= len(locks) <= 5:
            return _apply_repair(finding, locks[0])
    return finding


def normalize_findings(
    raw: Any,
    files_changed: Optional[List[str]] = None,
    pr_facts: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """Flatten agent output into one list of structured finding dicts.

    Glue only: no LLM. Copies evidence[0] → file when file is missing,
    normalizes slashes, drops empties and exact title+file duplicates.
    Repairs empty file/evidence from changed-path mentions before validate.
    """
    facts = pr_facts or {}
    files = list(files_changed or facts.get("files_changed") or [])
    classification = str(facts.get("classification") or "")
    lock_files = list(facts.get("lock_files") or [])
    items = _flatten_raw(raw)
    out: List[Dict[str, Any]] = []
    seen: set[Tuple[str, str]] = set()

    for item in items:
        d = _as_dict(item)
        if _is_empty_finding(d):
            continue

        d = repair_finding_paths(
            d,
            files,
            classification=classification,
            lock_files=lock_files,
        )

        evidence = _as_path_list(d.get("evidence"))
        file_val = _norm(str(d.get("file") or d.get("path") or ""))
        if not file_val and evidence:
            file_val = evidence[0]
        if file_val and file_val not in evidence:
            evidence = [file_val] + evidence

        d["file"] = file_val or None
        d["evidence"] = evidence
        d["title"] = str(d.get("title") or d.get("claim") or "").strip()
        d["claim"] = str(d.get("claim") or d["title"]).strip()
        d["description"] = str(d.get("description") or d.get("detail") or "").strip()
        d["reasoning"] = str(d.get("reasoning") or d["description"]).strip()
        d["recommendation"] = str(d.get("recommendation") or "").strip()
        d["category"] = str(d.get("category") or "review")
        d.setdefault("id", d.get("id") or "")
        try:
            d["confidence"] = float(d.get("confidence") or 0.5)
        except (TypeError, ValueError):
            d["confidence"] = 0.5
        d["severity"] = str(d.get("severity") or "medium")

        symbol = str(d.get("symbol") or "").strip()
        d["symbol"] = symbol if _looks_like_symbol(symbol) else None

        for key in ("start_line", "end_line"):
            val = d.get(key)
            if val is None or val == "":
                d[key] = None
            else:
                try:
                    d[key] = int(val)
                except (TypeError, ValueError):
                    d[key] = None

        key = (d["title"].lower(), d["file"] or "")
        if key in seen:
            continue
        seen.add(key)
        out.append(d)
    return out


# ── Validator ────────────────────────────────────────────────────────────────

def _text(f: Dict[str, Any]) -> str:
    parts = [
        str(f.get("title") or ""),
        str(f.get("description") or ""),
        str(f.get("detail") or ""),
        str(f.get("reasoning") or ""),
        str(f.get("claim") or ""),
        str(f.get("recommendation") or ""),
    ]
    return " ".join(parts)


def _evidence_paths(f: Dict[str, Any]) -> List[str]:
    paths = _as_path_list(f.get("evidence"))
    extra = f.get("file") or f.get("path")
    if extra:
        n = _norm(str(extra))
        if n and n not in paths:
            paths.append(n)
    return paths


def _path_in_allowed(path: str, allowed: Iterable[str]) -> Optional[str]:
    """Exact or suffix/basename match against files_changed / paths_in_diff."""
    path = _norm(path)
    if not path:
        return None
    path_l = path.lower()
    path_base = path_l.split("/")[-1]
    for a in allowed:
        a_n = _norm(a)
        if not a_n:
            continue
        a_l = a_n.lower()
        if path_l == a_l:
            return a_n
        if path_l.endswith("/" + a_l) or a_l.endswith("/" + path_l):
            return a_n
        if path_base and path_base == a_l.split("/")[-1]:
            return a_n
    return None


def _is_trivial(path: str) -> bool:
    p = _norm(path).lower()
    return any(t.lower() in p for t in TRIVIAL_PATHS)


def _is_source_path(path: str) -> bool:
    p = _norm(path).lower()
    return any(p.endswith(ext) for ext in CODE_EXTS)


def _symbol_known(
    symbol: str,
    *,
    diff_symbols: List[str],
    full_diff: str,
    evidence_paths: List[str],
) -> bool:
    if not symbol:
        return True
    parts = [p for p in symbol.replace("::", ".").split(".") if p]
    stems = [
        _norm(p).split("/")[-1].rsplit(".", 1)[0].lower()
        for p in evidence_paths
        if p
    ]
    hay = (full_diff or "")
    hay_l = hay.lower()
    syms_l = {s.lower() for s in diff_symbols if s}
    for p in parts:
        pl = p.lower()
        if pl in syms_l or pl in hay_l or pl in stems:
            return True
    if symbol.lower() in hay_l:
        return True
    return False


def validate_finding(
    finding: Any,
    *,
    files_changed: List[str],
    paths_in_diff: Optional[List[str]] = None,
    changed_symbols: Optional[List[str]] = None,
    full_diff: str = "",
) -> Tuple[bool, str]:
    """Deterministic accept/reject. No LLM. Fail-fast L1–L5.

    Returns (ok, reason) where reason is a stable code on failure, else "ok".
    """
    f = finding if isinstance(finding, dict) else _as_dict(finding)
    allowed = list(
        dict.fromkeys(
            [_norm(x) for x in (files_changed or []) + (paths_in_diff or []) if x]
        )
    )
    if not allowed:
        return False, "no_changed_paths"

    ev_paths = _evidence_paths(f)

    # L1 — Evidence exists
    if not ev_paths:
        return False, "missing_evidence_path"

    # L2 — Evidence is in the PR
    matched: List[str] = []
    for p in ev_paths:
        hit = _path_in_allowed(p, allowed)
        if hit:
            matched.append(hit)
    if not matched:
        return False, "evidence_not_in_pr"

    code_changed = [p for p in allowed if _is_source_path(p)]

    # L3 — Trivial-file rule
    if code_changed and all(_is_trivial(m) for m in matched):
        return False, "trivial_evidence_only"

    # L4 — Claim talks about code, evidence is trivia
    text = _text(f)
    named_source = [
        p
        for p in code_changed
        if (p.split("/")[-1] and p.split("/")[-1] in text) or (p in text)
    ]
    if named_source and all(_is_trivial(m) for m in matched):
        return False, "discussed_code_but_cited_trivial_file"

    # L5 — Optional symbol check against identifiers in the diff
    explicit = f.get("symbol")
    symbols = [s for s in (changed_symbols or []) if s]
    if explicit and symbols:
        if not _symbol_known(
            str(explicit),
            diff_symbols=symbols,
            full_diff=full_diff,
            evidence_paths=matched,
        ):
            return False, "unknown_symbol"

    return True, "ok"


def filter_findings(
    findings: List[Any],
    *,
    files_changed: List[str],
    paths_in_diff: Optional[List[str]] = None,
    changed_symbols: Optional[List[str]] = None,
    full_diff: str = "",
) -> Dict[str, Any]:
    kept: List[Dict[str, Any]] = []
    dropped: List[Dict[str, Any]] = []
    for item in findings or []:
        d = item if isinstance(item, dict) else _as_dict(item)
        ok, reason = validate_finding(
            d,
            files_changed=files_changed,
            paths_in_diff=paths_in_diff,
            changed_symbols=changed_symbols,
            full_diff=full_diff,
        )
        if ok:
            kept.append(d)
        else:
            dropped.append({"finding": d, "reason": reason})
    return {"kept": kept, "dropped": dropped, "raw": len(findings or [])}


def log_validation(result: Dict[str, Any]) -> None:
    """Print KEEP/DROP lines plus totals. Mandatory for precision/recall."""
    kept = result.get("kept") or []
    dropped = result.get("dropped") or []
    raw = result.get("raw")
    if raw is None:
        raw = len(kept) + len(dropped)

    for item in dropped:
        f = item.get("finding") or {}
        if not isinstance(f, dict):
            f = _as_dict(f)
        print(
            f"[Grounding] DROP reason={item.get('reason')}\n"
            f"  title={f.get('title') or ''}\n"
            f"  file={f.get('file') or ''}\n"
            f"  evidence={f.get('evidence') or []}\n"
            f"  symbol={f.get('symbol') or ''}"
        )

    for f in kept:
        print(
            f"[Grounding] KEEP\n"
            f"  title={f.get('title') or ''}\n"
            f"  file={f.get('file') or ''}\n"
            f"  evidence={f.get('evidence') or []}"
        )

    print(f"[Grounding] raw={raw} kept={len(kept)} dropped={len(dropped)}")


def _category_bucket(cat: str) -> str:
    c = (cat or "").lower()
    if c in ("quality", "code_quality"):
        return "code_quality"
    if c in ("test", "testing"):
        return "testing"
    if c in ("correctness",):
        return "correctness"
    return c or "review"


def validate_findings_node(state: dict) -> dict:
    """LangGraph node: normalize → validate → log → pass kept only.

    After Phase 7.1 this runs after investigate. If classified_findings is
    present, only KEEP (including promoted PLAUSIBLE) is re-validated for 4.1.
    Direct unit tests still collect from specialist buckets.
    """
    from core.hypothesis import KEEP

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
    raw_counts = {"correctness": 0, "code_quality": 0, "testing": 0}
    classified_raw = state.get("classified_findings")
    if classified_raw is not None:
        for item in classified_raw:
            d = _as_dict(item)
            if str(d.get("hypothesis_status") or KEEP) != KEEP:
                continue
            cat = str(d.get("category") or "correctness")
            bucket = _category_bucket(cat)
            if bucket in raw_counts:
                raw_counts[bucket] += 1
            raw_items.append(d)
    else:
        for key, cat in buckets:
            src = list(state.get(key) or [])
            raw_counts[cat] = len(src)
            for item in src:
                d = _as_dict(item)
                d["category"] = d.get("category") or cat
                raw_items.append(d)

    normalized = normalize_findings(
        raw_items, files_changed=files_changed, pr_facts=facts
    )
    paths_in_diff = list(facts.get("paths_in_diff") or [])
    if not paths_in_diff and facts:
        paths_in_diff = list(_allowed_paths_from_facts(facts))
    full_diff = state.get("full_diff") or facts.get("full_diff") or ""
    changed_symbols = extract_diff_symbols(full_diff)

    result = filter_findings(
        normalized,
        files_changed=files_changed,
        paths_in_diff=paths_in_diff,
        changed_symbols=changed_symbols,
        full_diff=full_diff,
    )
    result["raw"] = len(normalized)
    log_validation(result)

    kept: List[Dict[str, Any]] = result["kept"]
    dropped = result["dropped"]
    for f in kept:
        f["hypothesis_status"] = KEEP

    by_cat = {"correctness": [], "code_quality": [], "testing": []}
    for f in kept:
        bucket = _category_bucket(str(f.get("category") or ""))
        if bucket in by_cat:
            by_cat[bucket].append(f)
        else:
            by_cat["correctness"].append(f)

    dropped_summaries = []
    for item in dropped:
        f = item.get("finding") or {}
        dropped_summaries.append(
            {
                "title": f.get("title"),
                "reason": item.get("reason"),
                "file": f.get("file"),
                "evidence": f.get("evidence"),
                "symbol": f.get("symbol"),
                "category": f.get("category"),
            }
        )

    def _meta(existing: Any, cat: str) -> dict:
        meta = dict(existing) if isinstance(existing, dict) else {}
        meta["raw"] = raw_counts.get(cat, meta.get("raw", 0))
        meta["grounded"] = len(by_cat.get(cat) or [])
        meta["validated"] = meta["grounded"]
        return meta

    report = {
        "ran": True,
        "raw": len(normalized),
        "kept": len(kept),
        "dropped": len(dropped),
        "dropped_summaries": dropped_summaries,
        "reasons": [d.get("reason") for d in dropped],
    }

    return {
        "validated_findings": kept,
        "findings": kept,
        "validation_report": report,
        "correctness_findings": by_cat["correctness"],
        "quality_findings": by_cat["code_quality"],
        "testing_findings": by_cat["testing"],
        "correctness_meta": _meta(state.get("correctness_meta"), "correctness"),
        "quality_meta": _meta(state.get("quality_meta"), "code_quality"),
        "testing_meta": _meta(state.get("testing_meta"), "testing"),
        "traces": [
            {
                "agent": "FindingValidator",
                "output": (
                    f"raw={report['raw']} kept={report['kept']} "
                    f"dropped={report['dropped']}"
                ),
            }
        ],
    }
