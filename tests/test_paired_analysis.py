"""Paired analysis validates identities and does not manufacture perfect metrics."""
import pytest

from benchmark.paired_analysis import ScoredCase, paired_analysis


def case(name="one", **changes):
    return ScoredCase(**{"case_id": name, "cluster_id": name, "source_input_id": "a" * 64,
                         "tp": 1, "fp": 0, "fn": 1, "clean_control": False,
                         "status": "completed", "latency_seconds": 1.0, **changes})


def test_counts_and_paired_recall_improvement_are_reproducible():
    baseline = [case("one"), case("two")]
    candidate = [case("one", tp=2, fn=0), case("two", tp=2, fn=0)]
    report = paired_analysis(baseline, candidate, samples=100)
    assert report == paired_analysis(baseline, candidate, samples=100)
    assert report["metrics"]["recall"]["delta"] == 0.5
    assert report["metrics"]["recall"]["delta_95_percentile_interval"] == [0.5, 0.5]
    assert report["metrics"]["fp_per_clean_pr"]["candidate"] is None


def test_no_predictions_does_not_create_perfect_precision():
    report = paired_analysis([case(tp=0, fn=2)], [case(tp=0, fn=2)], samples=100)
    assert report["metrics"]["precision"]["candidate"] is None
    assert report["metrics"]["precision"]["valid_bootstrap_samples"] == 0
    assert report["metrics"]["recall"]["candidate"] == 0


def test_related_cases_are_one_cluster_without_a_confidence_claim():
    cases = [case("one", cluster_id="repo"), case("two", cluster_id="repo")]
    report = paired_analysis(cases, cases, samples=100)
    assert report["independent_clusters"] == 1
    assert report["metrics"]["recall"]["delta_95_percentile_interval"] is None


@pytest.mark.parametrize("change", [
    {"source_input_id": "b" * 64}, {"cluster_id": "different"}, {"tp": 2, "fn": 2},
])
def test_different_inputs_or_labels_cannot_be_paired(change):
    with pytest.raises(ValueError, match="differ"):
        paired_analysis([case()], [case(**change)], samples=100)


def test_missing_or_duplicate_cases_are_rejected():
    with pytest.raises(ValueError, match="membership"):
        paired_analysis([case()], [case("different")], samples=100)
    with pytest.raises(ValueError, match="duplicate"):
        paired_analysis([case(), case()], [case()], samples=100)


def test_clean_controls_require_explicit_labels_and_include_failed_attempts():
    clean = case(tp=0, fn=0, fp=1, clean_control=True, status="failed")
    report = paired_analysis([clean], [clean], samples=100)
    assert report["metrics"]["fp_per_clean_pr"]["candidate"] == 1
    assert report["metrics"]["completion_rate"]["candidate"] == 0
    with pytest.raises(ValueError, match="reference defects"):
        case(clean_control=True)
