"""Human and machine readable benchmark reports."""
from __future__ import annotations
import json
from pathlib import Path
from typing import Any, Dict

def render_ascii(metrics: Dict[str, Any]) -> str:
    actionable = metrics.get("actionable") or {}
    decision = metrics.get("decision") or {}
    blocking = actionable.get("blocking_recall")
    blocking_text = "N/A" if blocking is None else f"{blocking:.2%}"
    def percent(value: Any) -> str:
        return "N/A" if value is None else f"{value:.2%}"
    safety = metrics.get("merge_safety") or {}
    def safety_rate(name):
        estimate = safety.get(name) or {}
        interval = estimate.get("wilson_95")
        return (f"{estimate.get('events', 0)}/{estimate.get('total', 0)} = {percent(estimate.get('rate'))}"
                + (f" (95% Wilson {percent(interval[0])}–{percent(interval[1])})" if interval else ""))
    return "\n".join([
        "CodeTurtle benchmark", "="*22,
        f"PRs       {metrics.get('prs',0)}",
        f"All gold  TP/FP/FN {metrics.get('tp',0)}/{metrics.get('fp',0)}/{metrics.get('fn',0)}",
        f"All F1    {percent(metrics.get('f1'))}",
        f"Actionable TP/FP/FN {actionable.get('tp',0)}/{actionable.get('fp',0)}/{actionable.get('fn',0)}",
        f"Act P/R/F1 {percent(actionable.get('precision'))}/{percent(actionable.get('recall'))}/{percent(actionable.get('f1'))}",
        f"Blocking gold {actionable.get('blocking_gold_count', 0)}",
        f"Blocking recall {blocking_text}",
        f"FP / PR   {metrics.get('fp_per_pr') if metrics.get('fp_per_pr') is not None else 'N/A'}",
        f"Agent success {percent(metrics.get('agent_run_success_rate'))}",
        f"Decision accuracy {percent(decision.get('accuracy'))}",
        f"False MERGE / defective PRs {safety_rate('false_merge_given_defective')}",
        f"Defective / labeled MERGEs {safety_rate('defective_given_labeled_merge')}",
        f"Uncertain/unlabeled MERGEs {safety.get('unlabeled_or_uncertain_merges', 'N/A')}",
        f"Over/under block {percent(decision.get('over_blocking_rate'))}/{percent(decision.get('under_blocking_rate'))}",
    ])

def render_gate(gate: Dict[str, Any]) -> str:
    failed = [name for name, passed in (gate.get("checks") or {}).items() if passed is False]
    unmeasured = [name for name, passed in (gate.get("checks") or {}).items() if passed is None]
    return f"Release gate: {'PASS' if gate.get('passed') else 'FAIL'}" + (
        f" ({', '.join(failed + [name + ': N/A' for name in unmeasured])})"
        if failed or unmeasured else ""
    )

def write_aggregate(path: Path, aggregate: Dict[str, Any]) -> None:
    from core.review.artifacts import write_json_atomic
    write_json_atomic(path, aggregate)
