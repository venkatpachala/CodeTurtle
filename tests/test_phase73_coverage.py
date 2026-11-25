"""Phase 7.3 — coverage-aware final. Empty KEEP + low pack ratio cannot MERGE."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

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
        self.assertEqual(rec, "MERGE")
        self.assertEqual(reason, "no_findings")
        self.assertNotIn("coverage", reason)

    def test_empty_keep_high_coverage_merge(self):
        rec, reason = decide(
            [],
            classification="source",
            coverage=HIGH,
            files_changed=[LOADER],
            risk="medium",
        )
        self.assertEqual(rec, "MERGE")
        self.assertEqual(reason, "no_findings")

    def test_supported_medium_wins_over_low_coverage(self):
        rec, reason = decide(
            [
                {
                    "file": LOADER,
                    "title": "load swallows errors",
                    "claim": "errors are swallowed",
                    "verification_status": "supported",
                    "verify_status": "verified",
                    "severity": "concern",
                    "kind": "defect",
                }
            ],
            classification="source",
            coverage=LOW,
            files_changed=[LOADER],
        )
        self.assertEqual(rec, "REQUEST_CHANGES")
        self.assertEqual(reason, "verified_medium")

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
        self.assertNotEqual(rec, "REQUEST_CHANGES")
        self.assertEqual(rec, "MERGE")
        self.assertEqual(reason, "no_findings")

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
        self.assertEqual(rec, "MERGE")
        self.assertEqual(reason, "no_findings")

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
        self.assertEqual(rec, "MERGE")
        rec2 = recommendation_from_verification(
            [], classification="source", risk="low"
        )
        self.assertEqual(rec2, "MERGE")
