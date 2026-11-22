"""Safety denominators and truth provenance must survive scoring and reporting."""
import json

import pytest
from pydantic import ValidationError

from benchmark.dataset import load_dataset
from benchmark.evaluator import evaluate_pr
from benchmark.gates import evaluate_release_gate
from benchmark.metrics import aggregate_metrics
from benchmark.pr_truth import PRTruth, merge_safety, rate_estimate
from benchmark.reports import render_ascii


def truth(label="reviewed_clean"):
    return PRTruth(label=label, base_sha="a"*40, head_sha="b"*40, labelers=("human-1",),
                   evidence=("audit.json",), rationale="Pinned source audit")


def prediction(decision="MERGE"):
    return {"decision": decision, "target": {"base_sha": "a"*40, "head_sha": "b"*40}, "findings": []}


def test_empty_gold_is_unknown_and_never_counts_as_clean_or_decision_success():
    pred = prediction()
    evaluation = evaluate_pr(pred, [])
    result = aggregate_metrics([evaluation], [pred])
    assert evaluation["pr_truth"] == "unlabeled"
    assert result["actionable"]["clean_pr_count"] == 0
    assert result["decision"]["accuracy"] is None
    safety = result["merge_safety"]
    assert safety["unlabeled_or_uncertain_merges"] == 1
    assert safety["all_merge_defect_rate_label_bounds"] == [0, 1]
    assert safety["defective_given_labeled_merge"]["rate"] is None


def test_clean_truth_requires_provenance_and_matching_pinned_target():
    with pytest.raises(ValidationError): PRTruth.model_validate({"label": "reviewed_clean"})
    pred = prediction()
    evaluation = evaluate_pr(pred, [], pr_truth=truth())
    assert aggregate_metrics([evaluation], [pred])["actionable"]["clean_pr_count"] == 1
    pred["target"]["head_sha"] = "c"*40
    with pytest.raises(ValueError, match="BASE/HEAD"): evaluate_pr(pred, [], pr_truth=truth())
    with pytest.raises(ValueError, match="conflicts"): evaluate_pr(prediction(), [{"comment": "bug"}], pr_truth=truth())


def test_both_false_merge_denominators_include_failures_and_unknown_merges():
    evaluations = [{"pr_truth": label} for label in ["defective", "defective", "reviewed_clean", "uncertain", "defective"]]
    predictions = [prediction(x) for x in ["MERGE", "REQUEST_CHANGES", "MERGE", "MERGE", None]]
    safety = merge_safety(evaluations, predictions)
    assert safety["false_merge_given_defective"]["events"] == 1
    assert safety["false_merge_given_defective"]["total"] == 3
    assert safety["defective_given_labeled_merge"]["rate"] == 0.5
    assert safety["all_merge_defect_rate_label_bounds"] == [1/3, 2/3]
    assert safety["no_verdict"] == 1


def test_zero_errors_in_small_sample_is_not_zero_risk():
    estimate = rate_estimate(0, 10)
    assert estimate["rate"] == 0
    assert estimate["wilson_95"][1] == pytest.approx(0.2775328)
    assert rate_estimate(0, 400)["wilson_95"][1] < 0.01
    assert rate_estimate(0, 0)["rate"] is None
    with pytest.raises(ValueError): rate_estimate(2, 1)


def test_dataset_labels_reach_scoring_reports_and_release_gate(tmp_path):
    source = tmp_path / "dataset.json"
    source.write_text(json.dumps({"https://github.com/a/b/pull/1": {"pr_truth": truth().model_dump(mode="json")}}))
    pr = load_dataset(str(source))[0]
    pred = prediction()
    ev = evaluate_pr(pred, [], pr_truth=pr.pr_truth)
    metrics = aggregate_metrics([ev], [pred])
    assert "Defective / labeled MERGEs 0/1" in render_ascii(metrics)
    assert evaluate_release_gate(metrics, {})["checks"]["false_merge_upper_95"] is None
    assert evaluate_release_gate(metrics, {})["checks"]["pr_truth_complete"] is True


def test_mismatched_pairing_is_never_silently_scored():
    assert merge_safety([{}], [prediction(), prediction()])["measured"] is False
    with pytest.raises(ValueError, match="identities"):
        merge_safety([{"pr_url": "a"}], [{"pr_url": "b"}])
