"""Real-schema evaluator invariants for the frozen-reviewer validation phase."""

from __future__ import annotations

from pathlib import Path

import pytest

from benchmark.gates import evaluate_release_gate
from benchmark.gold import load_adjudications, statuses_for_pr
from benchmark.failure_adjudication import load_failure_adjudications
from benchmark.issue_trace import FailureStage, trace_gold_issues
from benchmark.metrics import aggregate_metrics
from benchmark.reports import render_ascii, render_gate
from benchmark.splits import assert_disjoint, load_registered_splits, load_split


def test_registered_splits_are_disjoint() -> None:
    root = Path(__file__).resolve().parents[1] / "benchmark" / "datasets"
    splits = load_registered_splits(root)
    assert {split.split for split in splits} == {"development", "validation", "test"}
    assert_disjoint(*splits)
    development = next(split for split in splits if split.split == "development")
    assert development.eligible_for_headline_metrics is False
    assert development.used_for_system_design is True


def test_split_rejects_development_headline_eligibility(tmp_path: Path) -> None:
    source = tmp_path / "bad.json"
    source.write_text(
        '{"split":"development","prs":["https://github.com/a/b/pull/1"],'
        '"eligible_for_headline_metrics":true}', encoding="utf-8",
    )
    with pytest.raises(ValueError, match="headline"):
        load_split(source)


def test_blocking_recall_is_unmeasured_without_blocking_gold() -> None:
    evaluations = [{
        "tp": 1, "fp": 0, "fn": 0,
        "matches": [{"golden": {"category": "bug", "severity": "medium"}}],
        "false_negatives": [], "false_positives": [],
    }]
    predictions = [{"decision": "REQUEST_CHANGES", "telemetry": {"latency_seconds": 1}}]
    metrics = aggregate_metrics(evaluations, predictions)
    assert metrics["actionable"]["blocking_gold_count"] == 0
    assert metrics["actionable"]["blocking_recall"] is None
    gate = evaluate_release_gate(metrics, {"min_prs": 1})
    assert gate["checks"]["blocking_recall"] is None
    assert gate["checks"]["minimum_clean_sample"] is False
    assert gate["passed"] is False
    assert "Blocking recall N/A" in render_ascii(metrics)
    assert "blocking_recall: N/A" in render_gate(gate)


def test_precision_is_unmeasured_when_no_findings_are_emitted() -> None:
    evaluation = [{
        "tp": 0, "fp": 0, "fn": 1, "matches": [],
        "false_negatives": [{"golden": {"category": "bug", "severity": "high"}}],
        "false_positives": [],
    }]
    metrics = aggregate_metrics(evaluation, [{"decision": "MERGE"}])
    assert metrics["precision"] is None
    assert metrics["recall"] == 0.0
    assert metrics["f1"] is None
    assert metrics["actionable"]["precision"] is None
    gate = evaluate_release_gate(metrics, {"min_prs": 1})
    assert gate["checks"]["actionable_precision"] is None
    assert "N/A/0.00%/N/A" in render_ascii(metrics)


def test_unadjudicated_gold_is_explicit() -> None:
    statuses = statuses_for_pr("https://github.com/a/b/pull/1", [{"comment": "bug"}], {})
    assert statuses[0].gold_id == "G-001"
    assert statuses[0].status == "adjudication_required"


def test_development_gold_has_explicit_questionable_label() -> None:
    root = Path(__file__).resolve().parents[1]
    adjudications = load_adjudications(root / "benchmark" / "adjudications" / "signals_v3_dev.json")
    url = "https://github.com/ai-code-review-evaluation/discourse-graphite/pull/1"
    statuses = statuses_for_pr(url, [{}] * 4, adjudications)
    assert [item.status for item in statuses] == [
        "confirmed", "confirmed", "confirmed", "adjudication_required"
    ]


def test_validation_failure_audit_is_issue_specific() -> None:
    root = Path(__file__).resolve().parents[1]
    entries = load_failure_adjudications(root / "benchmark" / "adjudications" / "validation_v1_failures.json")
    assert len(entries) == 5
    assert entries[("https://github.com/ai-code-review-evaluation/sentry-greptile/pull/2", "G-003")]["failure_stage"] == "HYPOTHESIS_MISS"


def test_trace_does_not_attribute_unrelated_pr_drop_to_gold() -> None:
    prediction = {
        "pr_url": "https://github.com/a/b/pull/1",
        "coverage_total": 2,
        "pipeline_trace": [{
            "candidate_id": "C-001", "stage": "verifier", "status": "dropped",
            "title": "cache eviction drops active key", "drop_reason": "disproved",
        }],
        "agent_runs": [{"status": "VALID_CANDIDATES", "hypotheses": [{"hypothesis": "cache eviction drops active key"}]}],
    }
    goldens = [{"comment": "authorization check missing from payment endpoint"}]
    result = trace_gold_issues(prediction, {"matches": []}, goldens)
    assert result[0].candidate_id is None
    assert result[0].failure_stage == FailureStage.UNATTRIBUTED.value
    assert result[0].grounded is None


def test_trace_links_distinctive_candidate_drop() -> None:
    prediction = {
        "pr_url": "https://github.com/a/b/pull/1",
        "pipeline_trace": [{
            "candidate_id": "C-002", "stage": "positioner", "status": "dropped",
            "title": "invalid gifsicle resize dimensions", "drop_reason": "no_line",
        }],
    }
    goldens = [{"comment": "invalid gifsicle resize dimensions for animated uploads"}]
    result = trace_gold_issues(prediction, {"matches": []}, goldens)
    assert result[0].candidate_id == "C-002"
    assert result[0].failure_stage == FailureStage.POSITIONING_FAILURE.value


def test_trace_attributes_proof_only_with_related_healthy_bundle() -> None:
    prediction = {
        "pr_url": "https://github.com/a/b/pull/1",
        "agent_runs": [{
            "status": "VALID_EMPTY", "candidate_count": 0,
            "hypotheses": [{"id": "H-001", "hypothesis": "invalid pagination cursor offset"}],
            "tool_calls": [{"hypothesis_id": "H-001", "request": {"tool": "read_hunk"}, "result": {"text": "offset=-1"}}],
        }],
    }
    result = trace_gold_issues(
        prediction, {"matches": []}, [{"comment": "invalid pagination cursor offset bypasses bounds"}]
    )
    assert result[0].hypothesis_generated is True
    assert result[0].evidence_retrieved is True
    assert result[0].failure_stage == FailureStage.PROOF_MISS.value
