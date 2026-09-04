"""Phase 7.3 — coverage-aware final. Empty KEEP + low pack ratio cannot MERGE."""

from __future__ import annotations

import io
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.github_review import should_post
from core.verification.policy import (
    clamp_recommendation,
    coverage_score,
    decide,
    recommendation_from_verification,
)

LOADER = "api/loaders/sqlserver_loader.py"
LOCK = "package-lock.json"

LOW = {"units_total": 20, "units_packed": 2, "units_omitted": 18, "source_units": 18}
HIGH = {"units_total": 10, "units_packed": 10, "units_omitted": 0, "source_units": 10}
ZERO_UNITS = {"units_total": 0, "units_packed": 0, "units_omitted": 0, "source_units": 0}


class TestDecideTable(unittest.TestCase):
    def test_lockfile_only_wins_over_low_coverage(self):
        rec, reason = decide(
            [],
            classification="lockfile-only",
            coverage={"units_total": 10, "units_packed": 1, "source_units": 0},
            files_changed=[LOCK],
        )
        self.assertEqual(rec, "COMMENT")
        self.assertEqual(reason, "lockfile-only")

    def test_empty_keep_low_coverage_comment(self):
        rec, reason = decide(
            [],
            classification="source",
            coverage=LOW,
            files_changed=[LOADER],
            risk="low",
        )
        self.assertEqual(rec, "COMMENT")
        self.assertEqual(reason, "insufficient_coverage")

    def test_empty_keep_high_coverage_merge(self):
        rec, reason = decide(
            [],
            classification="source",
            coverage=HIGH,
            files_changed=[LOADER],
            risk="medium",
        )
        self.assertEqual(rec, "MERGE")
        self.assertEqual(reason, "no_validated_issues")

    def test_supported_medium_wins_over_low_coverage(self):
        rec, reason = decide(
            [
                {
                    "file": LOADER,
                    "verification_status": "supported",
                    "severity": "concern",
                }
            ],
            classification="source",
            coverage=LOW,
            files_changed=[LOADER],
        )
        self.assertEqual(rec, "REQUEST_CHANGES")
        self.assertEqual(reason, "supported_medium")

    def test_uncertain_only_comment_even_if_packed(self):
        rec, reason = decide(
            [
                {
                    "file": LOADER,
                    "verification_status": "uncertain",
                    "severity": "nit",
                }
            ],
            classification="source",
            coverage=HIGH,
            files_changed=[LOADER],
        )
        self.assertEqual(rec, "COMMENT")
        self.assertEqual(reason, "keep_non_blocking")

    def test_source_files_zero_units_is_low(self):
        ratio, low = coverage_score(
            ZERO_UNITS, classification="source", files_changed=[LOADER]
        )
        self.assertEqual(ratio, 0.0)
        self.assertTrue(low)
        rec, reason = decide(
            [],
            classification="source",
            coverage=ZERO_UNITS,
            files_changed=[LOADER],
        )
        self.assertEqual(rec, "COMMENT")
        self.assertEqual(reason, "insufficient_coverage")

    def test_lockfile_coverage_score_enough(self):
        ratio, low = coverage_score(
            {"units_total": 1, "units_packed": 1, "source_units": 0},
            classification="lockfile-only",
            files_changed=[LOCK],
        )
        self.assertEqual(ratio, 1.0)
        self.assertFalse(low)

    def test_legacy_without_coverage_keeps_risk_comment(self):
        rec = recommendation_from_verification(
            [], classification="source", risk="medium"
        )
        self.assertEqual(rec, "COMMENT")
        rec2 = recommendation_from_verification(
            [], classification="source", risk="low"
        )
        self.assertEqual(rec2, "MERGE")


class TestClampCoverage(unittest.TestCase):
    def test_llm_merge_low_coverage_clamped_comment(self):
        from core.agents import final_recommender
        from core.models import ReviewOutput

        def fake_gen(**kwargs):
            return ReviewOutput(
                summary="Looks fine",
                recommendation="MERGE",
                confidence=0.9,
            )

        state = {
            "validated_findings": [],
            "findings": [],
            "files_changed": [LOADER],
            "pr_facts": {
                "classification": "source",
                "files_changed": [LOADER],
            },
            "review_coverage": LOW,
            "pr_understanding": {"summary": "loader", "risk_level": "low"},
            "review_plan": {"risk_level": "low"},
            "verification_report": {"ran": True, "suggested_recommendation": "COMMENT"},
        }
        buf = io.StringIO()
        with redirect_stdout(buf), patch("core.agents.gateway") as gw:
            gw.generate_structured.side_effect = fake_gen
            out = final_recommender(state)
        self.assertEqual(out["recommendation"], "COMMENT")
        self.assertEqual(out["policy_reason"], "insufficient_coverage")
        self.assertTrue(out["coverage_low"])
        self.assertIn("insufficient_coverage", buf.getvalue())
        self.assertIn("[Coverage]", buf.getvalue())

    def test_llm_request_changes_low_coverage_empty_keep_stays_comment(self):
        from core.agents import final_recommender
        from core.models import ReviewOutput

        def fake_gen(**kwargs):
            return ReviewOutput(
                summary="must block",
                recommendation="REQUEST_CHANGES",
                confidence=0.9,
            )

        state = {
            "validated_findings": [],
            "findings": [],
            "files_changed": [LOADER],
            "pr_facts": {"classification": "source", "files_changed": [LOADER]},
            "review_coverage": LOW,
            "pr_understanding": {"summary": "loader", "risk_level": "low"},
            "verification_report": {"ran": True},
        }
        with patch("core.agents.gateway") as gw:
            gw.generate_structured.side_effect = fake_gen
            out = final_recommender(state)
        self.assertEqual(out["recommendation"], "COMMENT")
        self.assertEqual(out["policy_reason"], "insufficient_coverage")

    def test_high_coverage_empty_keep_allows_merge(self):
        from core.agents import final_recommender
        from core.models import ReviewOutput

        def fake_gen(**kwargs):
            return ReviewOutput(
                summary="No validated issues found",
                recommendation="MERGE",
                confidence=0.8,
            )

        state = {
            "validated_findings": [],
            "findings": [],
            "files_changed": [LOADER],
            "pr_facts": {"classification": "source", "files_changed": [LOADER]},
            "review_coverage": HIGH,
            "pr_understanding": {"summary": "loader", "risk_level": "medium"},
            "verification_report": {"ran": True},
        }
        with patch("core.agents.gateway") as gw:
            gw.generate_structured.side_effect = fake_gen
            out = final_recommender(state)
        self.assertEqual(out["recommendation"], "MERGE")
        self.assertEqual(out["policy_reason"], "no_validated_issues")
        self.assertFalse(out["coverage_low"])

    def test_clamp_helper_insufficient_coverage(self):
        self.assertEqual(
            clamp_recommendation(
                "MERGE", "COMMENT", "source", policy_reason="insufficient_coverage"
            ),
            "COMMENT",
        )
        self.assertEqual(
            clamp_recommendation(
                "REQUEST_CHANGES",
                "COMMENT",
                "source",
                policy_reason="insufficient_coverage",
            ),
            "COMMENT",
        )

    def test_dry_run_does_not_post(self):
        self.assertFalse(should_post(dry_run=True, comment=False))


class TestGithubClampUsesCoverage(unittest.TestCase):
    def test_clamped_decision_low_coverage_comment(self):
        from core.github_review import clamped_decision

        state = {
            "recommendation": "MERGE",
            "validated_findings": [],
            "files_changed": [LOADER],
            "pr_facts": {"classification": "source", "files_changed": [LOADER]},
            "review_coverage": LOW,
            "pr_understanding": {"risk_level": "low"},
            "verification_report": {"ran": True, "suggested_recommendation": "MERGE"},
        }
        self.assertEqual(clamped_decision(state), "COMMENT")


if __name__ == "__main__":
    unittest.main(verbosity=2)
