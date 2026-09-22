"""Human and machine readable benchmark reports."""
from __future__ import annotations
import json
from pathlib import Path
from typing import Any, Dict

def render_ascii(metrics: Dict[str, Any]) -> str:
    actionable = metrics.get("actionable") or {}
    decision = metrics.get("decision") or {}
    return "\n".join([
        "CodeTurtle benchmark", "="*22,
        f"PRs       {metrics.get('prs',0)}",
        f"All gold  TP/FP/FN {metrics.get('tp',0)}/{metrics.get('fp',0)}/{metrics.get('fn',0)}",
        f"All F1    {metrics.get('f1',0):.2%}",
        f"Actionable TP/FP/FN {actionable.get('tp',0)}/{actionable.get('fp',0)}/{actionable.get('fn',0)}",
        f"Act P/R/F1 {actionable.get('precision',0):.2%}/{actionable.get('recall',0):.2%}/{actionable.get('f1',0):.2%}",
        f"Blocking recall {actionable.get('blocking_recall',0):.2%}",
        f"FP / PR   {metrics.get('fp_per_pr',0):.2f}",
        f"Agent success {metrics.get('agent_run_success_rate',0):.2%}",
        f"Decision accuracy {decision.get('accuracy',0):.2%}",
        f"Over/under block {decision.get('over_blocking_rate',0):.2%}/{decision.get('under_blocking_rate',0):.2%}",
    ])

def render_gate(gate: Dict[str, Any]) -> str:
    failed = [name for name, passed in (gate.get("checks") or {}).items() if not passed]
    return f"Release gate: {'PASS' if gate.get('passed') else 'FAIL'}" + (
        f" ({', '.join(failed)})" if failed else ""
    )

def write_aggregate(path: Path, aggregate: Dict[str, Any]) -> None:
    path.write_text(json.dumps(aggregate, indent=2, sort_keys=True), encoding="utf-8")
