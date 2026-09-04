"""ChangeUnit: one diff hunk as the specialist LLM view. Deterministic. No LLM."""

from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple, Union

from pydantic import BaseModel, Field

from core.pr_facts import _is_docs_or_trivia, is_lockfile, is_source_file, normalize_path
from core.verification.diff_index import DiffIndex, Hunk, build_diff_index

EXCERPT_CAP = 2500
LOCKFILE_PACK_LINES = 20
DEFAULT_PACK_CHARS = 12000

MUTATION_NEEDLES = (
    "delete(",
    ".commit(",
    "execute(",
    "DROP ",
    "graph.delete",
    "unlink",
    "rmtree",
)
IO_NEEDLES = (
    "requests.",
    "httpx",
    "connect(",
)

_TEST_BASENAME_RE = re.compile(
    r"^(test_.*\.py|.*_test\.py|.*\.test\.(ts|tsx|js|jsx))$",
    re.I,
)
_DEF_RE = re.compile(
    r"^\s*(?:async\s+)?def\s+([A-Za-z_][A-Za-z0-9_]*)",
    re.M,
)
_CLASS_RE = re.compile(
    r"^\s*class\s+([A-Za-z_][A-Za-z0-9_]*)",
    re.M,
)
_FUNC_RE = re.compile(
    r"^\s*(?:export\s+)?(?:async\s+)?function\s+([A-Za-z_][A-Za-z0-9_]*)",
    re.M,
)
_CALL_RE = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]{2,})\s*\(")
_DOT_RE = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)+)")
_HEADER_CTX_RE = re.compile(r"@@.*?@@\s*(.*)$")

_SYM_STOP = {
    "if", "for", "while", "return", "print", "self", "this", "class", "def",
    "async", "await", "true", "false", "none", "from", "import", "const",
    "let", "var", "new", "not", "and", "or", "try", "except", "catch",
    "with", "pass", "else", "elif", "switch", "case", "break", "continue",
    "yield", "raise", "super", "lambda", "assert", "len", "str", "int",
    "dict", "list", "set", "bool", "type", "range", "open", "log",
}


class ChangeUnit(BaseModel):
    id: str
    path: str
    start_line: int = 0
    end_line: int = 0
    symbols: List[str] = Field(default_factory=list)
    excerpt: str = ""
    n_added: int = 0
    n_removed: int = 0
    kind: str = "other"  # source | test | lockfile | docs | other
    risk_hint: str = "none"  # none | mutation | io | test


def unit_kind(path: str) -> str:
    n = normalize_path(path)
    base = n.split("/")[-1]
    if is_lockfile(n):
        return "lockfile"
    if _TEST_BASENAME_RE.match(base or ""):
        return "test"
    if _is_docs_or_trivia(n) or n.lower().endswith((".md", ".rst")):
        return "docs"
    if is_source_file(n):
        return "source"
    return "other"


def risk_hint(kind: str, excerpt: str) -> str:
    blob = excerpt or ""
    for needle in MUTATION_NEEDLES:
        if needle in blob:
            return "mutation"
    blob_l = blob.lower()
    for needle in IO_NEEDLES:
        if needle.lower() in blob_l:
            return "io"
    if kind == "test":
        return "test"
    return "none"


def extract_unit_symbols(added: str, header: str = "", excerpt: str = "") -> List[str]:
    found: List[str] = []
    added = added or ""
    ctx = ""
    m = _HEADER_CTX_RE.search(header or "")
    if m:
        ctx = m.group(1) or ""
    for rx in (_DEF_RE, _CLASS_RE, _FUNC_RE):
        found.extend(rx.findall(added))
        found.extend(rx.findall(ctx))
    for rx in (_DOT_RE, _CALL_RE):
        found.extend(rx.findall(added))
        found.extend(rx.findall(ctx))
    out: List[str] = []
    seen: set[str] = set()
    for s in found:
        if not s or s.lower() in _SYM_STOP:
            continue
        if s[0].isdigit():
            continue
        k = s.lower()
        if k in seen:
            continue
        seen.add(k)
        out.append(s)
        if len(out) >= 12:
            break
    return out


def _excerpt_for(hunk: Hunk, cap: int = EXCERPT_CAP) -> str:
    raw = hunk.raw or ""
    if len(raw) <= cap:
        return raw
    return raw[: cap - 1].rstrip() + "…"


def _n_lines(text: str) -> int:
    if not text:
        return 0
    return len(text.splitlines())


def build_change_units(
    full_diff: str,
    files_changed: Optional[Iterable[str]] = None,
    *,
    index: Optional[DiffIndex] = None,
) -> List[ChangeUnit]:
    """One ChangeUnit per non-empty hunk on filtered files_changed."""
    idx = index or build_diff_index(full_diff or "")
    wanted = [normalize_path(p) for p in (files_changed or []) if p]
    if wanted:
        paths = list(dict.fromkeys(wanted))
    else:
        paths = sorted(idx.file_set())

    units: List[ChangeUnit] = []
    n = 0
    for path in paths:
        hunks = idx.hunks_for(path)
        resolved = normalize_path(path)
        for h in hunks:
            n_added = _n_lines(h.added)
            n_removed = _n_lines(h.removed)
            if n_added == 0 and n_removed == 0:
                continue
            n += 1
            kind = unit_kind(h.file or resolved)
            excerpt = _excerpt_for(h)
            start = int(h.new_start or 0)
            end = int(h.new_end or start)
            unit = ChangeUnit(
                id=f"CU-{n:03d}",
                path=normalize_path(h.file or resolved),
                start_line=start,
                end_line=end if end >= start else start,
                symbols=extract_unit_symbols(h.added or "", h.header or "", excerpt),
                excerpt=excerpt,
                n_added=n_added,
                n_removed=n_removed,
                kind=kind,
                risk_hint=risk_hint(kind, excerpt),
            )
            units.append(unit)
    _log_units(units)
    return units


def _log_units(units: Sequence[ChangeUnit]) -> None:
    counts = {"source": 0, "test": 0, "lockfile": 0, "docs": 0, "other": 0}
    for u in units:
        if u.kind in counts:
            counts[u.kind] += 1
        else:
            counts["other"] += 1
    print(
        f"[ChangeUnits] n={len(units)} source={counts['source']} "
        f"test={counts['test']} lockfile={counts['lockfile']} docs={counts['docs']}"
    )
    for u in units:
        print(
            f"[ChangeUnits] {u.id} {u.path} L{u.start_line}-{u.end_line} "
            f"symbols={u.symbols} risk={u.risk_hint}"
        )


def _as_unit(item: Union[ChangeUnit, Dict[str, Any]]) -> ChangeUnit:
    if isinstance(item, ChangeUnit):
        return item
    return ChangeUnit.model_validate(item)


def _pack_rank(u: ChangeUnit) -> tuple:
    if u.kind == "source" and u.risk_hint in ("mutation", "io"):
        return (0, 0)
    if u.kind == "source":
        return (1, 0)
    if u.kind == "test":
        return (2, 0)
    if u.kind == "lockfile":
        return (3, 0)
    if u.kind == "docs":
        return (4, 0)
    return (5, 0)


def _render_unit(u: ChangeUnit, *, lockfile_trim: bool) -> str:
    excerpt = u.excerpt or ""
    if lockfile_trim and u.kind == "lockfile":
        lines = excerpt.splitlines()
        if len(lines) > LOCKFILE_PACK_LINES:
            excerpt = "\n".join(lines[:LOCKFILE_PACK_LINES]) + "\n…"
    symbols = ", ".join(u.symbols) if u.symbols else "(none)"
    return (
        f"### {u.id} {u.path}:{u.start_line}-{u.end_line}\n"
        f"symbols: {symbols}\n"
        f"risk: {u.risk_hint}\n"
        f"{excerpt}"
    ).rstrip()


def format_units(
    units: Sequence[Union[ChangeUnit, Dict[str, Any]]],
    *,
    max_chars: int = DEFAULT_PACK_CHARS,
    lockfile_only: bool = False,
) -> Tuple[str, Dict[str, int]]:
    """Pack units by risk. Skip lockfile/docs unless lockfile-only. Cap max_chars."""
    parsed = [_as_unit(u) for u in (units or [])]
    source_n = sum(1 for u in parsed if u.kind == "source")
    has_code = any(u.kind in ("source", "test") for u in parsed)
    include_lock_docs = bool(lockfile_only) or not has_code

    ranked = sorted(parsed, key=_pack_rank)
    selected: List[ChangeUnit] = []
    for u in ranked:
        if u.kind in ("lockfile", "docs") and not include_lock_docs:
            continue
        selected.append(u)

    blocks: List[str] = []
    used = 0
    packed_n = 0
    for u in selected:
        trim = u.kind == "lockfile"
        block = _render_unit(u, lockfile_trim=trim)
        extra = len(block) + (2 if blocks else 0)
        if packed_n > 0 and used + extra > max_chars:
            break
        blocks.append(block)
        used += extra
        packed_n += 1

    omitted = max(0, len(parsed) - packed_n)
    packed_text = "\n\n".join(blocks) if blocks else "(no change units)"
    coverage = {
        "units_total": len(parsed),
        "units_packed": packed_n,
        "units_omitted": omitted,
        "source_units": source_n,
    }
    print(
        f"[ChangeUnits] packed={coverage['units_packed']} "
        f"omitted={coverage['units_omitted']} source={source_n}"
    )
    if packed_n:
        print(f"[ChangeUnits] units_packed={packed_n} omitted={omitted}")
    return packed_text, coverage


def attach_change_units(
    state: dict,
    *,
    max_chars: int = DEFAULT_PACK_CHARS,
) -> dict:
    """Build units + packed LLM view. full_diff on state is unchanged."""
    facts = state.get("pr_facts") if isinstance(state.get("pr_facts"), dict) else {}
    files = list(facts.get("files_changed") or state.get("files_changed") or [])
    full_diff = state.get("full_diff") or facts.get("full_diff") or ""
    classification = str(facts.get("classification") or "")
    units = build_change_units(full_diff, files)
    packed, coverage = format_units(
        units,
        max_chars=max_chars,
        lockfile_only=(classification == "lockfile-only"),
    )
    print(
        f"[ChangeUnits] coverage total={coverage['units_total']} "
        f"packed={coverage['units_packed']} omitted={coverage['units_omitted']} "
        f"source={coverage['source_units']}"
    )
    return {
        "change_units": [u.model_dump() for u in units],
        "review_diff": packed,
        "review_coverage": coverage,
    }


def change_units_node(state: dict) -> dict:
    """LangGraph: after facts on state, before understanding / specialists."""
    if state.get("change_units") is not None and state.get("review_diff"):
        return {}
    return attach_change_units(state)


def specialist_code_view(state: dict, max_chars: int = DEFAULT_PACK_CHARS) -> str:
    """LLM-facing hunk pack. Never a raw 14k prefix of full_diff when units exist."""
    if state.get("review_diff"):
        text = str(state.get("review_diff") or "")
        if max_chars and len(text) > max_chars:
            return text[:max_chars]
        return text
    units = state.get("change_units")
    facts = state.get("pr_facts") if isinstance(state.get("pr_facts"), dict) else {}
    lockfile_only = str(facts.get("classification") or "") == "lockfile-only"
    if units is not None:
        packed, _ = format_units(
            units, max_chars=max_chars, lockfile_only=lockfile_only
        )
        return packed
    attached = attach_change_units(state, max_chars=max_chars)
    state.update(attached)
    return str(attached.get("review_diff") or "(no change units)")
