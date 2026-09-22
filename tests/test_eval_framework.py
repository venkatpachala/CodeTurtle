"""tests/test_eval_framework.py — Tests for the evaluation framework.

NO MOCKING. Uses synthetic data that follows the real benchmark schema.
"""

from __future__ import annotations

import pytest
from benchmark.evaluator import evaluate_pr
from evals.review.findings import (
    FindingMatcher,
    GoldenIssue,
    PredictedFinding,
    compute_finding_metrics,
    match_findings_to_golden,
)
from evals.review.decision import compute_decision_metrics
from evals.review.survival import SurvivalFunnel, aggregate_survival_from_results
from evals.review.failure import (
    attribute_failures, FailureReport, CANDIDATE_MISS, PROOF_MISS,
    AGENT_FAILURE, HYPOTHESIS_MISS, EVIDENCE_MISS,
)


# ── FindingMatcher ─────────────────────────────────────────────────────────────

class TestFindingMatcher:

    def test_semantic_match_obvious(self):
        """Clearly related prediction matches golden."""
        matcher = FindingMatcher(semantic_threshold=0.1)
        pred = [PredictedFinding(
            id="P-001",
            path="sentry/models/audit.py",
            line=42,
            body="OptimizedCursorPaginator uses negative slice which raises IndexError",
            category="bug",
        )]
        gold = [GoldenIssue(
            id="G-001",
            comment="The OptimizedCursorPaginator uses negative slice indices which raises IndexError",
            severity="High",
            category="bug",
        )]
        matches, unmatched_preds, unmatched_gold = matcher.match(pred, gold)
        assert len(matches) == 1
        assert len(unmatched_preds) == 0
        assert len(unmatched_gold) == 0
        assert matches[0].confidence > 0.1


class TestDeterministicBenchmarkMatcher:

    def test_long_review_matches_distinctive_gold_not_generic_issue(self):
        prediction = {
            "review_comments": [{
                "path": "app/assets/javascripts/discourse/lib/utilities.js",
                "line": 182,
                "body": (
                    "Incorrect error message for file size exceeding 10MB. "
                    "var maxSizeKB = 10 * 1024 ignores site settings and makes "
                    "the client maximum diverge from configured limits."
                ),
            }]
        }
        goldens = [
            {"comment": "tempfile.size may never terminate due to stale cached size and infinite loops"},
            {"comment": "Hardcoding maxSizeKB = 10 * 1024 ignores Discourse.SiteSettings and makes the client limit diverge"},
        ]
        result = evaluate_pr(prediction, goldens)
        assert result["tp"] == 1
        assert result["matches"][0]["golden_index"] == 1

    def test_no_match_when_unrelated(self):
        """Unrelated prediction does not match golden."""
        matcher = FindingMatcher(semantic_threshold=0.1)
        pred = [PredictedFinding(
            id="P-001",
            path="foo.py",
            line=1,
            body="missing docstring for function calculate_tax",
            category="style",
        )]
        gold = [GoldenIssue(
            id="G-001",
            comment="SQL injection vulnerability in user authentication login endpoint",
            severity="Critical",
            category="security",
        )]
        matches, unmatched_preds, unmatched_gold = matcher.match(pred, gold)
        assert len(matches) == 0
        assert len(unmatched_preds) == 1
        assert len(unmatched_gold) == 1

    def test_category_boost(self):
        """Category match boosts confidence."""
        matcher = FindingMatcher(semantic_threshold=0.1)
        pred = [PredictedFinding(
            id="P-001", path="a.py", line=10,
            body="concurrent access to shared state without lock",
            category="concurrency",
        )]
        gold = [GoldenIssue(
            id="G-001",
            comment="thread-safe access required for shared cache dictionary",
            severity="High",
            category="concurrency",
        )]
        matches, _, _ = matcher.match(pred, gold)
        assert len(matches) == 1
        assert matches[0].category_match is True
        assert matches[0].match_type == "semantic_cat"

    def test_one_to_one_assignment(self):
        """Greedy assignment ensures each golden matched at most once."""
        matcher = FindingMatcher(semantic_threshold=0.05)
        preds = [
            PredictedFinding(id="P-001", path="a.py", line=1,
                             body="null pointer exception dereference crash", category="bug"),
            PredictedFinding(id="P-002", path="a.py", line=1,
                             body="null pointer dereference causes crash bug", category="bug"),
        ]
        gold = [GoldenIssue(
            id="G-001", comment="null pointer dereference bug crash", severity="High", category="bug"
        )]
        matches, unmatched_preds, unmatched_gold = matcher.match(preds, gold)
        assert len(matches) == 1
        assert len(unmatched_preds) == 1
        assert len(unmatched_gold) == 0


# ── Match findings to golden ───────────────────────────────────────────────────

class TestMatchFindingsToGolden:

    def test_empty_predictions_all_fn(self):
        """Zero predictions → all golden issues become FN."""
        golden_map = {
            "https://github.com/org/repo/pull/1": [
                GoldenIssue(id="G-001", comment="memory leak in cache eviction", severity="High", category="bug"),
                GoldenIssue(id="G-002", comment="missing null check", severity="Medium", category="bug"),
            ]
        }
        pr_results = match_findings_to_golden({}, golden_map)
        assert len(pr_results) == 1
        r = pr_results[0]
        assert r.tp == 0
        assert r.fp == 0
        assert r.fn == 2
        assert r.precision == 0.0
        assert r.recall == 0.0

    def test_perfect_match(self):
        """Exact semantic match → TP=all."""
        pr_url = "https://github.com/org/repo/pull/2"
        golden_map = {pr_url: [
            GoldenIssue(id="G-001", comment="cursor paginator negative slice raises IndexError", severity="High", category="bug"),
        ]}
        pr_results_map = {pr_url: [
            {"path": "a.py", "line": 42, "body": "cursor paginator negative slice raises IndexError"}
        ]}
        results = match_findings_to_golden(pr_results_map, golden_map, matcher=FindingMatcher(semantic_threshold=0.05))
        assert len(results) == 1
        r = results[0]
        assert r.tp == 1
        assert r.fp == 0
        assert r.fn == 0
        assert r.precision == 1.0
        assert r.recall == 1.0
        assert r.f1 == 1.0


# ── Compute finding metrics ───────────────────────────────────────────────────

class TestComputeFindingMetrics:

    def test_aggregation_correct(self):
        """Aggregation sums per-PR correctly."""
        from evals.review.findings import PRFindingResult
        results = [
            PRFindingResult(pr_url="https://github.com/x/y/pull/1", tp=2, fp=1, fn=3, golden_count=5, predicted_count=3),
            PRFindingResult(pr_url="https://github.com/x/y/pull/2", tp=0, fp=0, fn=2, golden_count=2, predicted_count=0),
        ]
        m = compute_finding_metrics(results)
        assert m.total_tp == 2
        assert m.total_fp == 1
        assert m.total_fn == 5
        assert m.prs_evaluated == 2
        assert m.prs_with_predictions == 1
        assert m.prs_with_any_tp == 1
        assert abs(m.precision - 2/3) < 0.001
        assert abs(m.recall - 2/7) < 0.001

    def test_zero_predictions_zero_precision(self):
        """Zero predictions → precision undefined → 0.0."""
        from evals.review.findings import PRFindingResult
        results = [PRFindingResult(pr_url="x", tp=0, fp=0, fn=5, golden_count=5, predicted_count=0)]
        m = compute_finding_metrics(results)
        assert m.precision == 0.0
        assert m.recall == 0.0
        assert m.f1 == 0.0

    def test_bootstrap_ci_shape(self):
        """Bootstrap CI returns (lo, hi) tuples."""
        from evals.review.findings import PRFindingResult
        results = [
            PRFindingResult(pr_url=f"x/{i}", tp=i % 3, fp=1, fn=2, golden_count=3, predicted_count=i%3+1)
            for i in range(10)
        ]
        m = compute_finding_metrics(results)
        assert len(m.precision_ci) == 2
        assert len(m.recall_ci) == 2
        assert m.precision_ci[0] <= m.precision_ci[1]
        assert m.recall_ci[0] <= m.recall_ci[1]


# ── Decision metrics ──────────────────────────────────────────────────────────

class TestDecisionMetrics:

    def test_perfect_predictions(self):
        gold = ["MERGE", "REQUEST_CHANGES", "COMMENT"]
        pred = ["MERGE", "REQUEST_CHANGES", "COMMENT"]
        m = compute_decision_metrics(pred, gold)
        assert m.accuracy == 1.0
        assert m.macro_f1 == 1.0

    def test_all_merge_under_blocking(self):
        """Predicting all MERGE gives under-blocking rate."""
        gold = ["REQUEST_CHANGES", "REQUEST_CHANGES", "MERGE"]
        pred = ["MERGE", "MERGE", "MERGE"]
        m = compute_decision_metrics(pred, gold)
        assert abs(m.accuracy - 1/3) < 0.001
        assert abs(m.under_blocking_rate - 2/3) < 0.001
        assert m.over_blocking_rate == 0.0

    def test_confusion_matrix_filled(self):
        gold = ["MERGE", "COMMENT", "REQUEST_CHANGES", "MERGE"]
        pred = ["MERGE", "MERGE", "MERGE", "COMMENT"]
        m = compute_decision_metrics(pred, gold)
        assert m.confusion["MERGE"]["MERGE"] == 1
        assert m.confusion["MERGE"]["COMMENT"] == 1
        assert m.confusion["COMMENT"]["MERGE"] == 1
        assert m.confusion["REQUEST_CHANGES"]["MERGE"] == 1


# ── Failure attribution ───────────────────────────────────────────────────────

class TestFailureAttribution:

    def _golden(self, gid, comment="test issue", cat="bug", sev="High"):
        return GoldenIssue(id=gid, comment=comment, severity=sev, category=cat)

    def test_candidate_miss_when_zero_candidates(self):
        result = {
            "pr_url": "https://github.com/x/y/pull/1",
            "telemetry": {"candidate_count": 0, "change_units_total": 100, "change_units_packed": 50},
            "review_comments": [],
        }
        golden_by_id = {"G-001": self._golden("G-001")}
        failures = attribute_failures("https://github.com/x/y/pull/1", ["G-001"], golden_by_id, result)
        assert len(failures) == 1
        assert failures[0].failure_type == CANDIDATE_MISS

    def test_proof_miss_when_incomplete_proof_drops(self):
        result = {
            "pr_url": "https://github.com/x/y/pull/1",
            "telemetry": {
                "candidate_count": 3,
                "change_units_total": 100,
                "change_units_packed": 50,
                "drop_reasons": {"incomplete_proof": 3},
            },
            "review_comments": [],
        }
        golden_by_id = {"G-001": self._golden("G-001")}
        failures = attribute_failures("x", ["G-001"], golden_by_id, result)
        assert len(failures) == 1
        assert failures[0].failure_type == PROOF_MISS

    def test_agent_failure_is_not_mislabeled_as_candidate_miss(self):
        result = {
            "telemetry": {"candidate_count": 0, "agent_runs": [{"status": "INVALID_JSON"}]},
            "coverage_total": 10,
            "coverage_packed": 10,
            "review_comments": [],
        }
        failures = attribute_failures("x", ["G-001"], {"G-001": self._golden("G-001")}, result)
        assert failures[0].failure_type == AGENT_FAILURE

    def test_hypothesis_and_evidence_stage_attribution(self):
        golden = {"G-001": self._golden("G-001")}
        base = {"coverage_total": 10, "coverage_packed": 10, "review_comments": []}
        no_hyp = {**base, "telemetry": {"agent_runs": [{"status": "VALID_EMPTY", "hypothesis_count": 0}]}}
        no_ev = {**base, "telemetry": {"agent_runs": [{"status": "VALID_EMPTY", "hypothesis_count": 1, "evidence_count": 0}]}}
        no_proof = {**base, "telemetry": {"agent_runs": [{"status": "VALID_EMPTY", "hypothesis_count": 1, "evidence_count": 2}]}}
        assert attribute_failures("x", ["G-001"], golden, no_hyp)[0].failure_type == HYPOTHESIS_MISS
        assert attribute_failures("x", ["G-001"], golden, no_ev)[0].failure_type == EVIDENCE_MISS
        assert attribute_failures("x", ["G-001"], golden, no_proof)[0].failure_type == PROOF_MISS


# ── Survival funnel ───────────────────────────────────────────────────────────

class TestSurvivalFunnel:

    def test_funnel_from_result_files(self):
        results = [
            {"pr_url": "p1", "coverage_total": 50, "coverage_packed": 30, "review_comments": [], "latency_seconds": 120.0},
            {"pr_url": "p2", "coverage_total": 80, "coverage_packed": 60, "review_comments": [], "latency_seconds": 250.0},
        ]
        golden_counts = {"p1": 3, "p2": 5}
        funnel = aggregate_survival_from_results(results, golden_counts)
        assert funnel.units_total == 130
        assert funnel.units_packed == 90
        assert funnel.prs_evaluated == 2
        assert funnel.candidates_generated == 0
        assert funnel.final_findings == 0
        rows = funnel.funnel_rows()
        assert any("Golden Issues" in r["stage"] for r in rows)
        assert any("Candidates Generated" in r["stage"] for r in rows)


def test_benchmark_prediction_keeps_agent_diagnostics():
    """Benchmark artifacts must distinguish an empty review from a broken run."""
    from core.runtime.models import ReviewResult

    result = ReviewResult(
        agent_runs=[{
            "bundle_id": "B-001",
            "status": "INVALID_JSON",
            "raw_outputs": ["I recommend MERGE"],
            "candidate_count": 0,
        }],
        pipeline_health={"healthy": False, "unhealthy_statuses": ["INVALID_JSON"]},
    )
    payload = result.to_dict()
    assert payload["agent_runs"][0]["status"] == "INVALID_JSON"
    assert payload["pipeline_health"]["healthy"] is False


def test_evaluator_results_are_deduplicated_by_pr_url(tmp_path):
    """A rerun must replace, never double-count, a prior PR artifact."""
    import json
    import time
    from evals.runner import _load_results

    older = tmp_path / "old.json"
    newer = tmp_path / "new.json"
    older.write_text(json.dumps({"pr_url": "https://github.com/o/r/pull/1", "decision": "MERGE"}))
    time.sleep(0.01)
    newer.write_text(json.dumps({"pr_url": "https://github.com/o/r/pull/1", "decision": "COMMENT"}))
    results = _load_results(tmp_path)
    assert len(results) == 1
    assert results[0]["decision"] == "COMMENT"


def test_benchmark_matcher_can_match_pathless_golden_semantically():
    from benchmark.evaluator import evaluate_pr

    prediction = {"review_comments": [{
        "path": "audit.py",
        "line": 42,
        "body": "OptimizedCursorPaginator negative slice raises IndexError",
    }]}
    goldens = [{
        "comment": "The OptimizedCursorPaginator uses negative slice indices and raises IndexError",
        "severity": "High",
        "category": "bug",
    }]
    result = evaluate_pr(prediction, goldens)
    assert result["tp"] == 1
    assert result["fp"] == 0
    assert result["fn"] == 0


def test_product_metrics_separate_actionable_from_style_gold():
    from benchmark.metrics import aggregate_metrics

    evaluations = [{
        "tp": 2, "fp": 0, "fn": 1,
        "matches": [
            {"golden": {"category": "bug", "severity": "High"}, "prediction": {}},
            {"golden": {"category": "style", "severity": "Low"}, "prediction": {}},
        ],
        "false_negatives": [{"golden": {"category": "security", "severity": "Critical"}}],
        "false_positives": [],
    }]
    metrics = aggregate_metrics(evaluations)
    assert metrics["actionable"]["tp"] == 1
    assert metrics["actionable"]["fp"] == 1
    assert metrics["actionable"]["fn"] == 1
    assert metrics["actionable"]["blocking_recall"] == 0.5


def test_decision_metric_uses_the_same_medium_threshold_as_review_policy():
    from benchmark.metrics import aggregate_metrics

    evaluations = [{
        "tp": 1, "fp": 0, "fn": 0,
        "matches": [{"golden": {"category": "bug", "severity": "Medium"}, "prediction": {}}],
        "false_negatives": [], "false_positives": [],
    }]
    metrics = aggregate_metrics(evaluations, [{"decision": "REQUEST_CHANGES"}])
    assert metrics["decision"]["accuracy"] == 1.0
    assert metrics["decision"]["over_blocking_rate"] == 0.0


def test_release_gate_requires_quality_and_sample_size():
    from benchmark.gates import evaluate_release_gate

    thresholds = {
        "min_prs": 10, "min_precision": 0.8, "min_blocking_recall": 0.6,
        "max_fp_per_pr": 0.3, "min_agent_success_rate": 0.95,
        "max_p95_latency_seconds": 300,
    }
    good = {
        "prs": 12, "fp_per_pr": 0.1, "agent_run_success_rate": 1.0,
        "actionable": {"precision": 0.9, "blocking_recall": 0.75},
        "decision": {"accuracy": 0.9, "over_blocking_rate": 0.05},
        "latency_seconds": {"p95": 120},
    }
    assert evaluate_release_gate(good, thresholds)["passed"] is True
    good["prs"] = 1
    gate = evaluate_release_gate(good, thresholds)
    assert gate["passed"] is False
    assert gate["checks"]["minimum_sample"] is False


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
