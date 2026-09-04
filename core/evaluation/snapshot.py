"""Build a ReviewSnapshot from LangGraph state or stable log prefixes."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, List, Optional

from pydantic import BaseModel, Field

from core.pr_facts import normalize_path


SNAPSHOT_PATH = Path("artifacts/last_review_snapshot.json")


class ReviewSnapshot(BaseModel):
    repo: str = ""
    number: int = 0
    classification: str = ""
    files_changed: List[str] = Field(default_factory=list)
    lock_files: List[str] = Field(default_factory=list)
    source_files: List[str] = Field(default_factory=list)
    investigate_skipped: bool = True
    skip_reason: Optional[str] = None
    hops: int = 0
    calls: int = 0
    hyp_files: List[str] = Field(default_factory=list)
    grounding_raw: int = 0
    grounding_kept: int = 0
    grounding_dropped: int = 0
    keep_files: List[str] = Field(default_factory=list)
    keep_verification_status: List[str] = Field(default_factory=list)
    keep_severity: List[str] = Field(default_factory=list)
    drop_reasons: List[str] = Field(default_factory=list)
    verify_supported: int = 0
    verify_uncertain: int = 0
    verify_unsupported: int = 0
    tests_touched_count: int = 0
    execute_skipped: bool = True
    execute_skip_reason: Optional[str] = None
    final_decision: str = ""
    suggested_policy: Optional[str] = None
    qdrant_used: bool = False


def _as_dict(obj: Any) -> dict:
    if obj is None:
        return {}
    if isinstance(obj, dict):
        return obj
    if hasattr(obj, "model_dump"):
        return obj.model_dump()
    return {}


def _norm_list(paths: List[Any]) -> List[str]:
    out: List[str] = []
    for p in paths or []:
        s = normalize_path(str(p or ""))
        if s:
            out.append(s)
    return out


def from_state(state: dict) -> ReviewSnapshot:
    """Preferred: read keys already on LangGraph review state."""
    state = state or {}
    facts = _as_dict(state.get("pr_facts"))
    inv = _as_dict(state.get("investigation_report"))
    val = _as_dict(state.get("validation_report"))
    vrep = _as_dict(state.get("verification_report"))
    ex = _as_dict(state.get("execution_report"))
    findings = list(state.get("validated_findings") or state.get("findings") or [])
    hyps = list(state.get("hypotheses") or [])

    keep_files: List[str] = []
    keep_status: List[str] = []
    keep_sev: List[str] = []
    for f in findings:
        d = _as_dict(f)
        fp = normalize_path(str(d.get("file") or ""))
        if not fp:
            continue
        keep_files.append(fp)
        keep_status.append(str(d.get("verification_status") or ""))
        keep_sev.append(str(d.get("severity") or ""))

    hyp_files: List[str] = []
    for h in hyps:
        d = _as_dict(h)
        fp = normalize_path(str(d.get("file") or d.get("file_hint") or ""))
        if fp:
            hyp_files.append(fp)

    drop_reasons = [str(r) for r in (val.get("reasons") or []) if r]
    if not drop_reasons:
        for item in val.get("dropped_summaries") or []:
            if isinstance(item, dict) and item.get("reason"):
                drop_reasons.append(str(item.get("reason")))

    traces = state.get("traces") or []
    qdrant = bool(state.get("kb") or state.get("engine"))
    blob = json.dumps(traces, default=str).lower() if traces else ""
    if "qdrant" in blob and "disabled" not in blob:
        qdrant = True
    if "graphify only" in blob or "qdrant disabled" in blob:
        qdrant = False

    rec = str(state.get("recommendation") or "").upper()
    md = _as_dict(state.get("merge_decision"))
    if not rec:
        rec = str(md.get("recommendation") or "").upper()

    tests_n = vrep.get("tests_touched")
    if tests_n is None:
        tests_n = sum(1 for f in findings if _as_dict(f).get("tests_touched"))

    return ReviewSnapshot(
        repo=str(state.get("repo") or facts.get("repo") or ""),
        number=int(state.get("number") or facts.get("pr_number") or 0),
        classification=str(facts.get("classification") or ""),
        files_changed=_norm_list(list(facts.get("files_changed") or state.get("files_changed") or [])),
        lock_files=_norm_list(list(facts.get("lock_files") or [])),
        source_files=_norm_list(list(facts.get("source_files") or [])),
        investigate_skipped=bool(inv.get("skipped", not inv.get("ran"))),
        skip_reason=(str(inv.get("reason") or "") or None),
        hops=int(inv.get("hops") or 0),
        calls=int(inv.get("calls") or 0),
        hyp_files=hyp_files,
        grounding_raw=int(val.get("raw") or 0),
        grounding_kept=int(val.get("kept") or len(keep_files)),
        grounding_dropped=int(val.get("dropped") or 0),
        keep_files=keep_files,
        keep_verification_status=keep_status,
        keep_severity=keep_sev,
        drop_reasons=drop_reasons,
        verify_supported=int(vrep.get("supported") or 0),
        verify_uncertain=int(vrep.get("uncertain") or 0),
        verify_unsupported=int(vrep.get("unsupported") or 0),
        tests_touched_count=int(tests_n or 0),
        execute_skipped=bool(ex.get("skipped", True)) if ex else True,
        execute_skip_reason=(str(ex.get("skip_reason") or "") or None) if ex else None,
        final_decision=rec,
        suggested_policy=(str(vrep.get("suggested_recommendation") or "") or None),
        qdrant_used=bool(qdrant),
    )


_PRFACTS_RE = re.compile(r"\[PRFacts\].*classification=(\S+)")
_INV_SKIP_RE = re.compile(r"\[Investigate\] skip reason=(.+)")
_INV_HOPS_RE = re.compile(r"\[Investigate\] hops=(\d+) calls=(\d+)")
_INV_FILE_RE = re.compile(r"\[Investigate\] \S+ .*file=(\S+)")
_KEEP_FILE_RE = re.compile(r"\[Grounding\] KEEP\s*\n\s*title=.*\n\s*file=(\S+)", re.M)
_KEEP_FILE_LINE_RE = re.compile(r"^\s*file=(\S+)", re.M)
_GROUND_RE = re.compile(r"\[Grounding\] raw=(\d+) kept=(\d+) dropped=(\d+)")
_VERIFY_RE = re.compile(
    r"\[Verify\] supported=(\d+) uncertain=(\d+) unsupported=(\d+)(?: tests_touched=(\d+))?"
)
_EXEC_SKIP_RE = re.compile(r"\[Execute\] skip reason=(\S+)")
_DECISION_RE = re.compile(r"Decision:\s*(MERGE|COMMENT|REQUEST_CHANGES)")
_SUGGESTED_RE = re.compile(r"suggested=(\S+)")
_PATHS_RE = re.compile(r"paths=\[([^\]]*)\]")


def from_logs(text: str, *, repo: str = "", number: int = 0) -> ReviewSnapshot:
    """Fallback when state is unavailable. Parses stable log prefixes only."""
    blob = text or ""
    classification = ""
    m = _PRFACTS_RE.search(blob)
    if m:
        classification = m.group(1)

    files_changed: List[str] = []
    pm = _PATHS_RE.search(blob)
    if pm:
        inner = pm.group(1)
        files_changed = [
            normalize_path(p.strip().strip("'\""))
            for p in inner.split(",")
            if p.strip()
        ]

    inv_skip = _INV_SKIP_RE.search(blob)
    hops_m = _INV_HOPS_RE.search(blob)
    hyp_files = [
        normalize_path(x) for x in _INV_FILE_RE.findall(blob) if x and x != "file="
    ]

    keep_files: List[str] = []
    in_keep = False
    for line in blob.splitlines():
        if "[Grounding] KEEP" in line:
            in_keep = True
            continue
        if in_keep and line.strip().startswith("file="):
            keep_files.append(normalize_path(line.strip()[5:]))
            in_keep = False
        elif in_keep and line.startswith("[Grounding]"):
            in_keep = False

    g = _GROUND_RE.search(blob)
    v = _VERIFY_RE.search(blob)
    ex = _EXEC_SKIP_RE.search(blob)
    dec = _DECISION_RE.search(blob)
    sug = _SUGGESTED_RE.search(blob)

    qdrant = "qdrant" in blob.lower() and "qdrant disabled" not in blob.lower()
    if "graphify only" in blob.lower() or "Qdrant disabled" in blob:
        qdrant = False

    if inv_skip:
        inv_skipped = True
    elif hops_m:
        inv_skipped = False
    else:
        inv_skipped = True

    return ReviewSnapshot(
        repo=repo,
        number=number,
        classification=classification,
        files_changed=files_changed,
        investigate_skipped=inv_skipped,
        skip_reason=inv_skip.group(1).strip() if inv_skip else None,
        hops=int(hops_m.group(1)) if hops_m else 0,
        calls=int(hops_m.group(2)) if hops_m else 0,
        hyp_files=hyp_files,
        grounding_raw=int(g.group(1)) if g else 0,
        grounding_kept=int(g.group(2)) if g else len(keep_files),
        grounding_dropped=int(g.group(3)) if g else 0,
        keep_files=keep_files,
        verify_supported=int(v.group(1)) if v else 0,
        verify_uncertain=int(v.group(2)) if v else 0,
        verify_unsupported=int(v.group(3)) if v else 0,
        tests_touched_count=int(v.group(4) or 0) if v else 0,
        execute_skipped=bool(ex) or "[Execute]" not in blob,
        execute_skip_reason=ex.group(1).strip() if ex else ("disabled" if "[Execute]" not in blob else None),
        final_decision=(dec.group(1) if dec else ""),
        suggested_policy=(sug.group(1) if sug else None),
        qdrant_used=qdrant,
    )


def write_review_snapshot(
    state: dict,
    path: Optional[Path] = None,
) -> ReviewSnapshot:
    snap = from_state(state)
    dest = path or SNAPSHOT_PATH
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(snap.model_dump_json(indent=2), encoding="utf-8")
    return snap


def load_snapshot(path: Path) -> ReviewSnapshot:
    data = json.loads(path.read_text(encoding="utf-8"))
    return ReviewSnapshot.model_validate(data)
