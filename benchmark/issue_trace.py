"""Conservative gold-issue survival tracing from recorded per-PR telemetry.

An issue is never assigned a stage merely because another issue in the same PR
had a drop. Unknown links remain UNATTRIBUTED with null stage observations.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any

from benchmark.evaluator import _tokens


class FailureStage(str, Enum):
    CHANGE_MISS = "CHANGE_MISS"
    SIGNAL_MISS = "SIGNAL_MISS"
    HYPOTHESIS_MISS = "HYPOTHESIS_MISS"
    EVIDENCE_UNAVAILABLE = "EVIDENCE_UNAVAILABLE"
    RETRIEVAL_MISS = "RETRIEVAL_MISS"
    PROOF_MISS = "PROOF_MISS"
    POSITIONING_FAILURE = "POSITIONING_FAILURE"
    GROUNDING_FAILURE = "GROUNDING_FAILURE"
    VERIFICATION_MISS = "VERIFICATION_MISS"
    FALSE_DISPROOF = "FALSE_DISPROOF"
    FILTER_FALSE_REJECTION = "FILTER_FALSE_REJECTION"
    MATCHER_FAILURE = "MATCHER_FAILURE"
    AGENT_FAILURE = "AGENT_FAILURE"
    INFRASTRUCTURE_FAILURE = "INFRASTRUCTURE_FAILURE"
    UNATTRIBUTED = "UNATTRIBUTED"


@dataclass
class GoldIssueTrace:
    gold_id: str
    pr_id: str
    change_represented: bool | None = None
    signal_generated: bool | None = None
    hypothesis_generated: bool | None = None
    evidence_requested: bool | None = None
    evidence_retrieved: bool | None = None
    proof_constructed: bool | None = None
    positioned: bool | None = None
    grounded: bool | None = None
    verification_status: str | None = None
    survived_filters: bool | None = None
    final_match: bool = False
    failure_stage: str | None = None
    candidate_id: str | None = None
    link_basis: str | None = None
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _strong_text_link(left: str, right: str) -> bool:
    a, b = _tokens(left), _tokens(right)
    overlap = len(a & b)
    return bool(a and b and overlap >= 2 and overlap / min(len(a), len(b)) >= 0.4)


def _candidate_link(golden_text: str, events: list[dict[str, Any]]) -> tuple[str | None, str | None]:
    by_id: dict[str, str] = {}
    for event in events:
        candidate_id = str(event.get("candidate_id") or "")
        title = str(event.get("title") or "")
        if candidate_id and title:
            by_id.setdefault(candidate_id, title)
    matches = [candidate_id for candidate_id, title in by_id.items() if _strong_text_link(golden_text, title)]
    if len(matches) == 1:
        return matches[0], "distinctive_title_token_overlap"
    return None, None


def trace_gold_issues(
    prediction: dict[str, Any], evaluation: dict[str, Any], goldens: list[dict[str, Any]],
) -> list[GoldIssueTrace]:
    pr_url = str(prediction.get("pr_url") or evaluation.get("pr_url") or "")
    events = [event for event in prediction.get("pipeline_trace") or [] if isinstance(event, dict)]
    runs = [run for run in prediction.get("agent_runs") or [] if isinstance(run, dict)]
    matched = {int(item["golden_index"]) for item in evaluation.get("matches") or []}
    healthy = {"VALID_CANDIDATES", "VALID_EMPTY", "LEGACY"}
    traces: list[GoldIssueTrace] = []

    for index, golden in enumerate(goldens):
        trace = GoldIssueTrace(gold_id=f"G-{index + 1:03d}", pr_id=pr_url, final_match=index in matched)
        text = str(golden.get("comment") or "")
        candidate_id, basis = _candidate_link(text, events)
        trace.candidate_id, trace.link_basis = candidate_id, basis
        linked = [event for event in events if event.get("candidate_id") == candidate_id] if candidate_id else []
        if linked:
            trace.proof_constructed = True
            trace.positioned = any(
                event.get("status") == "kept" and event.get("line") is not None
                and event.get("stage") in {"positioner", "reflector", "final"}
                for event in linked
            )
            trace.grounded = any(event.get("stage") == "reflector" and event.get("status") == "kept" for event in linked)
            if trace.positioned or trace.grounded:
                trace.change_represented = True
            verifier = [event for event in linked if event.get("stage") == "verifier"]
            if verifier:
                trace.verification_status = str(verifier[-1].get("status") or "")
            trace.survived_filters = any(event.get("stage") == "final" and event.get("status") == "kept" for event in linked)

        related_runs = [
            run for run in runs if any(
                isinstance(hypothesis, dict) and _strong_text_link(
                    text, str(hypothesis.get("hypothesis") or "") + " " + str(hypothesis.get("observation") or "")
                ) for hypothesis in run.get("hypotheses") or []
            )
        ]
        hypotheses = [
            hypothesis for run in related_runs for hypothesis in run.get("hypotheses") or []
            if isinstance(hypothesis, dict) and _strong_text_link(
                text, str(hypothesis.get("hypothesis") or "") + " " + str(hypothesis.get("observation") or "")
            )
        ]
        if hypotheses:
            trace.hypothesis_generated = True
            if any(str(hypothesis.get("id") or "").startswith("S-") for hypothesis in hypotheses):
                trace.signal_generated = True
            ids = {str(hypothesis.get("id") or "") for hypothesis in hypotheses}
            tools = [call for run in runs for call in run.get("tool_calls") or [] if isinstance(call, dict) and str(call.get("hypothesis_id") or "") in ids]
            trace.evidence_requested = bool(tools)
            if tools:
                trace.evidence_retrieved = any(bool(call.get("result")) for call in tools)

        if trace.final_match:
            trace.survived_filters = True
            traces.append(trace)
            continue

        drops = [event for event in linked if event.get("status") == "dropped"]
        if drops:
            drop = drops[-1]
            stage = str(drop.get("stage") or "")
            trace.failure_stage = {
                "positioner": FailureStage.POSITIONING_FAILURE.value,
                "reflector": FailureStage.GROUNDING_FAILURE.value,
                "verifier": FailureStage.VERIFICATION_MISS.value,
                "proof": FailureStage.PROOF_MISS.value,
                "classify": FailureStage.FILTER_FALSE_REJECTION.value,
            }.get(stage, FailureStage.UNATTRIBUTED.value)
            trace.notes.append(f"Linked candidate dropped at {stage}: {drop.get('drop_reason') or 'unknown'}")
        elif trace.survived_filters:
            trace.failure_stage = FailureStage.UNATTRIBUTED.value
            trace.notes.append("A title-related final candidate exists, but semantic equivalence requires manual review")
        elif runs and all(str(run.get("status") or "") not in healthy for run in runs):
            trace.failure_stage = FailureStage.AGENT_FAILURE.value
            trace.notes.append("Every bundle agent run was unhealthy")
        elif prediction.get("coverage_total") == 0:
            trace.failure_stage = FailureStage.CHANGE_MISS.value
        elif trace.hypothesis_generated and trace.evidence_requested and trace.evidence_retrieved is False:
            trace.failure_stage = FailureStage.RETRIEVAL_MISS.value
        elif (
            trace.hypothesis_generated and trace.evidence_retrieved is True and related_runs
            and all(run.get("status") in healthy and int(run.get("candidate_count") or 0) == 0 for run in related_runs)
        ):
            trace.failure_stage = FailureStage.PROOF_MISS.value
            trace.notes.append("Related healthy bundle runs retrieved evidence but produced no candidate")
        elif trace.hypothesis_generated and not linked:
            trace.failure_stage = FailureStage.UNATTRIBUTED.value
            trace.notes.append("Related hypothesis found, but no candidate can be linked with sufficient confidence")
        elif runs and all(not run.get("hypotheses") for run in runs):
            trace.failure_stage = FailureStage.HYPOTHESIS_MISS.value
        else:
            trace.failure_stage = FailureStage.UNATTRIBUTED.value
            trace.notes.append("Telemetry does not prove an issue-specific loss stage")
        traces.append(trace)
    return traces
