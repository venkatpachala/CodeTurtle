"""Build evidence-backed process coverage without inferring model understanding."""
from __future__ import annotations

from collections import Counter

from pydantic import ValidationError
from core.change_units import EXCERPT_CAP
from core.review.contract import ReviewCoverage, UnitAssessment


def _get(unit, key, default=""):
    return unit.get(key, default) if isinstance(unit, dict) else getattr(unit, key, default)


def collect_inspection(units: list, bundles: list, runs: list[dict]) -> ReviewCoverage:
    eligible = {str(_get(u, "id")): u for u in units if _get(u, "kind") in {"source", "test"}}
    packed = {str(_get(u, "id")) for b in bundles for u in b.units} & eligible.keys()
    scope = {uid: {"original_chars": _get(unit, "original_chars", None),
                   "captured_chars": _get(unit, "captured_chars", None),
                   "excerpt_truncated": bool(_get(unit, "excerpt_truncated", False))
                   or len(str(_get(unit, "excerpt"))) > EXCERPT_CAP}
             for uid, unit in eligible.items()}
    observed: dict[str, UnitAssessment] = {}
    recorded = {}
    healthy = {"VALID_CANDIDATES", "VALID_EMPTY"}
    by_bundle = {b.id: b for b in bundles}
    for run in runs:
        semantic = run.get("discovery_protocol") == "semantic-v1"
        if run.get("status") not in healthy and not semantic:
            continue
        bundle = by_bundle.get(run.get("bundle_id"))
        permitted = ({str(x["unit_id"]) for x in run.get("admission", []) if x.get("selected")}
                     if semantic and run.get("admission") else {str(_get(u, "id")) for u in (bundle.units[:12] if bundle else [])})
        for raw in run.get("assessments") or []:
            if not isinstance(raw, dict):
                continue
            uid = str(raw.get("unit_id") or "")
            if semantic and uid in packed:
                recorded[uid] = raw
            if semantic and raw.get("status") != "inspected":
                continue
            if uid not in eligible or uid not in permitted:
                continue
            # The prompt only includes this bounded slice. A truncated unit is
            # packed but cannot be claimed fully inspected.
            if scope[uid]["excerpt_truncated"]:
                continue
            refs = raw.get("evidence_refs")
            if not isinstance(refs, list) or uid not in refs:
                continue
            try:
                observed[uid] = UnitAssessment(unit_id=uid, path=_get(eligible[uid], "path"),
                    status="inspected", behavioral_delta=raw.get("behavioral_delta", ""),
                    hypothesis_outcome=raw.get("hypothesis_outcome", ""), evidence_refs=[uid], **scope[uid])
            except ValidationError:
                continue
    assessments = []
    for uid, unit in eligible.items():
        assessment = recorded.get(uid, {})
        assessments.append(observed.get(uid) or UnitAssessment(unit_id=uid, path=_get(unit, "path"),
            status="omitted" if uid not in packed else "unknown",
            reason="not_packed" if uid not in packed else "excerpt_truncated" if scope[uid]["excerpt_truncated"]
                   else assessment.get("reason") or "missing_or_incomplete_assessment",
            **scope[uid]))
    excluded = Counter(_get(unit, "kind", "other") for unit in units
                       if _get(unit, "kind") not in {"source", "test"})
    return ReviewCoverage(eligible=len(eligible), packed=len(packed), inspected=len(observed),
                          assessments=assessments, excluded_by_kind=dict(excluded))


def unresolved_hypotheses(runs: list[dict], candidates: list, dropped: list[dict]) -> list[dict]:
    unresolved = []
    for run in runs:
        outcomes = {str(x.get("hypothesis_id")): x for x in run.get("hypothesis_outcomes") or [] if isinstance(x, dict)}
        for hyp in run.get("hypotheses") or []:
            hid = str(hyp.get("id") or "")
            outcome = outcomes.get(hid, {})
            linked = [c for c in candidates if c.bundle_id == run.get("bundle_id") and c.hypothesis_id == hid]
            verified = any(c.verify_status == "verified" for c in linked)
            # A proof writer's self-reported rejection is not verified disproof.
            disproved = any(c.verify_status == "disproved" for c in linked)
            if not verified and not disproved:
                unresolved.append({"bundle_id": run.get("bundle_id"), "hypothesis_id": hid,
                    "file": hyp.get("file"), "reason": outcome.get("reason") or "proof_not_substantiated"})
    for drop in dropped:
        if drop.get("drop_reason") in {"incomplete_proof", "no_line", "PLAUSIBLE_BUT_UNPROVEN", "uncertain", "verify_limit", "verification_limit", "unproven", "no_execution_path"}:
            unresolved.append({"file": drop.get("file"), "hypothesis_id": drop.get("hypothesis_id"),
                               "reason": drop.get("drop_reason")})
    return unresolved
