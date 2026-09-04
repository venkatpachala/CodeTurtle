"""Seed failure-path hypotheses from mutation/io ChangeUnits. Deterministic. No LLM."""

from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Optional, Sequence, Union

from pydantic import BaseModel, Field

from core.change_units import ChangeUnit, _DEF_RE
from core.pr_facts import is_lockfile, normalize_path

MAX_UNITS_SCANNED = 8
MAX_FAILURE_PATH_HYPS = 3

# Longer / more specific tokens first for the `mutation` field.
MUTATION_TOKENS = (
    "graph.delete",
    "os.remove",
    "write_text",
    "TRUNCATE",
    "DROP ",
    ".delete(",
    ".commit(",
    "execute(",
    "unlink",
    "dump(",
    "rmtree",
    "delete(",
)

FOLLOW_ON = (
    ("load(", "load"),
    ("refresh_", "refresh"),
    ("reload", "reload"),
    ("close(", "close"),
    ("return False", "return False"),
    ("raise ", "raise"),
    ("commit", "commit"),
)

_EXCEPT_RE = re.compile(r"\bexcept\b|\braise\b")


class FailurePathHyp(BaseModel):
    file: str
    symbol: str = ""
    start_line: Optional[int] = None
    claim: str = ""
    mutation: str = ""
    next_step: str = ""
    source_unit_id: str = ""
    evidence: List[str] = Field(default_factory=list)

    def as_finding(self, index: int = 1) -> dict:
        title = (
            f"{self.mutation} before {self.next_step}".strip()
            or "failure path after mutation"
        )
        return {
            "id": f"fp-{index}",
            "agent": "FailurePathExtractor",
            "failure_path": True,
            "category": "correctness",
            "severity": "medium",
            "title": title[:120],
            "claim": self.claim,
            "file": self.file,
            "symbol": self.symbol or None,
            "start_line": self.start_line,
            "evidence": list(self.evidence or ([self.file] if self.file else [])),
            "source_unit_id": self.source_unit_id,
            "mutation": self.mutation,
            "next_step": self.next_step,
            "needs_investigation": True,
            "risk_hint": "mutation",
            "question": (
                f"callers of {self.symbol}" if self.symbol else ""
            ),
        }


def _as_unit(item: Union[ChangeUnit, Dict[str, Any]]) -> Optional[ChangeUnit]:
    if isinstance(item, ChangeUnit):
        return item
    if isinstance(item, dict):
        try:
            return ChangeUnit.model_validate(item)
        except Exception:
            return None
    return None


def _plus_text(excerpt: str) -> str:
    parts: List[str] = []
    for ln in (excerpt or "").splitlines():
        if ln.startswith("+") and not ln.startswith("+++"):
            parts.append(ln[1:])
    return "\n".join(parts)


def _first_mutation(blob: str) -> Optional[str]:
    for tok in MUTATION_TOKENS:
        if tok in blob:
            return tok.strip()
    return None


def _follow_ons(blob: str, mutation: str) -> List[str]:
    found: List[str] = []
    for needle, label in FOLLOW_ON:
        if needle in blob:
            if label.lower() in mutation.lower() or mutation.lower() in label.lower():
                continue
            if label not in found:
                found.append(label)
    return found


def _pick_symbol(unit: ChangeUnit, excerpt: str) -> str:
    skip = ("delete", "commit", "execute", "unlink", "dump", "write", "remove")
    for s in unit.symbols or []:
        sl = (s or "").lower()
        if not s or any(b in sl for b in skip):
            continue
        if "." in s and s.split(".")[-1].lower() in skip:
            continue
        return s
    blob = (excerpt or "").replace("\t", " ")
    for m in _DEF_RE.finditer(blob):
        name = m.group(1)
        if name and name.lower() not in skip:
            return name
    plus = _plus_text(excerpt)
    for m in _DEF_RE.finditer(plus):
        name = m.group(1)
        if name:
            return name
    return str((unit.symbols or [""])[0] if unit.symbols else "")


def _claim(mutation: str, next_step: str) -> str:
    mut = mutation or "mutation"
    nxt = next_step or "the next step"
    return (
        f"{mut} runs before {nxt}; if {nxt} fails, prior mutation may not roll back."
    )


def extract_failure_paths(
    units: Sequence[Union[ChangeUnit, Dict[str, Any]]],
    *,
    files_changed: Optional[Iterable[str]] = None,
    classification: str = "",
) -> List[FailurePathHyp]:
    """Scan mutation/io source units. Max 3 hyps. Dedup (file, symbol, mutation)."""
    if classification == "lockfile-only":
        print("[FailurePaths] skip")
        return []
    parsed: List[ChangeUnit] = []
    for raw in units or []:
        u = _as_unit(raw)
        if u is None:
            continue
        if is_lockfile(u.path) or u.kind == "lockfile":
            continue
        if u.kind != "source":
            continue
        if u.risk_hint not in ("mutation", "io"):
            continue
        parsed.append(u)
        if len(parsed) >= MAX_UNITS_SCANNED:
            break

    if not parsed:
        print("[FailurePaths] units_scanned=0 emitted=0")
        return []

    allowed = {normalize_path(p) for p in (files_changed or []) if p}
    emitted: List[FailurePathHyp] = []
    seen: set[tuple] = set()

    def _try_emit(u: ChangeUnit, mutation: str, next_step: str) -> None:
        if len(emitted) >= MAX_FAILURE_PATH_HYPS:
            return
        path = normalize_path(u.path)
        if allowed and path not in allowed:
            # still emit — 7.1 may mark PLAUSIBLE via tokens
            pass
        symbol = _pick_symbol(u, u.excerpt or "")
        key = (path, symbol or "", mutation)
        if key in seen:
            return
        seen.add(key)
        hyp = FailurePathHyp(
            file=path,
            symbol=symbol,
            start_line=int(u.start_line or 0) or None,
            claim=_claim(mutation, next_step),
            mutation=mutation,
            next_step=next_step,
            source_unit_id=u.id,
            evidence=[path] if path else [],
        )
        emitted.append(hyp)
        print(
            f"[FailurePaths] {u.id} {mutation} → {next_step} "
            f"file={path} symbol={symbol}"
        )

    for i, u in enumerate(parsed):
        if len(emitted) >= MAX_FAILURE_PATH_HYPS:
            break
        plus = _plus_text(u.excerpt or "")
        mutation = _first_mutation(plus)
        if not mutation:
            mutation = _first_mutation(u.excerpt or "")
        if not mutation:
            continue
        blob = (u.excerpt or "") + "\n" + plus
        follows = _follow_ons(blob, mutation)
        if not follows and i + 1 < len(parsed) and parsed[i + 1].path == u.path:
            nxt = parsed[i + 1]
            follows = _follow_ons(
                (nxt.excerpt or "") + "\n" + _plus_text(nxt.excerpt or ""),
                mutation,
            )
        if not follows and _EXCEPT_RE.search(blob):
            follows = ["raise"]
        if not follows:
            continue
        _try_emit(u, mutation, follows[0])

    print(
        f"[FailurePaths] units_scanned={len(parsed)} emitted={len(emitted)}"
    )
    return emitted


def extract_failure_paths_node(state: dict) -> dict:
    """LangGraph: after change_units, before classify. No LLM."""
    facts = state.get("pr_facts") if isinstance(state.get("pr_facts"), dict) else {}
    classification = str(facts.get("classification") or "")
    files = list(facts.get("files_changed") or state.get("files_changed") or [])
    units = list(state.get("change_units") or [])
    if not units:
        full_diff = state.get("full_diff") or facts.get("full_diff") or ""
        if full_diff:
            from core.change_units import build_change_units

            units = build_change_units(full_diff, files)
    if classification == "lockfile-only":
        print("[FailurePaths] skip")
        return {
            "failure_path_findings": [],
            "failure_path_report": {
                "skipped": True,
                "units_scanned": 0,
                "emitted": 0,
            },
            "traces": [
                {"agent": "FailurePathExtractor", "output": "skip lockfile-only"}
            ],
        }
    hyps = extract_failure_paths(
        units, files_changed=files, classification=classification
    )
    findings = [h.as_finding(i + 1) for i, h in enumerate(hyps)]
    report = {
        "skipped": False,
        "units_scanned": min(
            MAX_UNITS_SCANNED,
            sum(
                1
                for u in units
                if isinstance(u, dict)
                and u.get("kind") == "source"
                and u.get("risk_hint") in ("mutation", "io")
            ),
        ),
        "emitted": len(findings),
    }
    return {
        "failure_path_findings": findings,
        "failure_path_report": report,
        "traces": [
            {
                "agent": "FailurePathExtractor",
                "output": f"emitted={len(findings)}",
            }
        ],
    }
