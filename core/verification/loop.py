"""LangGraph node: stamp validated findings with hunk-level verification."""

from __future__ import annotations

from typing import Any, Dict, List

from core.verification.hunk_verifier import verify_findings
from core.verification.policy import recommendation_from_verification


def verify_findings_node(state: dict) -> dict:
    findings = list(state.get("validated_findings") or state.get("findings") or [])
    facts = state.get("pr_facts") or {}
    files_changed = list(
        facts.get("files_changed") or state.get("files_changed") or []
    )
    full_diff = state.get("full_diff") or ""

    stamped, records = verify_findings(
        findings,
        full_diff,
        files_changed=files_changed,
    )
    n_sup = sum(1 for r in records if r.status == "supported")
    n_unc = sum(1 for r in records if r.status == "uncertain")
    n_uns = sum(1 for r in records if r.status == "unsupported")
    n_tests = sum(1 for r in records if r.tests_touched)
    print(
        f"[Verify] supported={n_sup} uncertain={n_unc} unsupported={n_uns} "
        f"tests_touched={n_tests}/{len(records)}"
    )

    classification = str(facts.get("classification") or "")
    understanding = state.get("pr_understanding") or {}
    risk = ""
    if isinstance(understanding, dict):
        risk = str(understanding.get("risk_level") or "")
    plan = state.get("review_plan") or {}
    if isinstance(plan, dict) and plan.get("risk_level"):
        risk = str(plan.get("risk_level") or risk)
    suggested = recommendation_from_verification(
        stamped, classification=classification, risk=risk or "medium"
    )

    by_cat = {"correctness": [], "code_quality": [], "testing": []}
    for f in stamped:
        cat = str(f.get("category") or "")
        if cat in ("quality", "code_quality"):
            by_cat["code_quality"].append(f)
        elif cat in ("test", "testing"):
            by_cat["testing"].append(f)
        else:
            by_cat["correctness"].append(f)

    report = {
        "ran": True,
        "supported": n_sup,
        "uncertain": n_unc,
        "unsupported": n_uns,
        "tests_touched": n_tests,
        "tests_touched_of": len(records),
        "suggested_recommendation": suggested,
        "records": [r.model_dump() for r in records],
    }
    return {
        "validated_findings": stamped,
        "findings": stamped,
        "verification_report": report,
        "correctness_findings": by_cat["correctness"],
        "quality_findings": by_cat["code_quality"],
        "testing_findings": by_cat["testing"],
        "traces": [
            {
                "agent": "ClaimVerifier",
                "output": (
                    f"supported={n_sup} uncertain={n_unc} unsupported={n_uns} "
                    f"suggested={suggested}"
                ),
            }
        ],
    }
