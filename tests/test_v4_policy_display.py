"""Regression tests for defect classification and severity policy."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


LOADER = "pkg/api/loader.py"


class TestHedgeAndCoveragePolicy(unittest.TestCase):
    def test_three_potential_claims_are_comment(self):
        from core.verification.policy import decide

        findings = [
            {
                "file": LOADER,
                "title": "Potential UUID collision in source_trial_ids",
                "claim": "IDs may not belong to the source job",
                "severity": "medium",
                "verification_status": "supported",
                "kind": "defect",
                "confidence": 0.0,
            },
            {
                "file": LOADER,
                "title": "Potential missing guard on regrade",
                "claim": "regrade might skip validation",
                "severity": "medium",
                "verification_status": "supported",
                "kind": "defect",
                "confidence": 0.2,
            },
            {
                "file": LOADER,
                "title": "Potential empty selection",
                "claim": "possible empty source_job_id",
                "severity": "medium",
                "verification_status": "supported",
                "kind": "defect",
                "confidence": 0.0,
            },
        ]
        rec, reason = decide(
            findings,
            classification="source",
            coverage={"units_total": 10, "units_packed": 2, "source_units": 8},
            files_changed=[LOADER],
        )
        self.assertNotEqual(rec, "REQUEST_CHANGES")
        self.assertNotEqual(reason, "supported_medium")
        self.assertNotIn("coverage", reason)
        self.assertEqual(rec, "MERGE")
        self.assertEqual(reason, "no_findings")

    def test_verified_empty_source_job_id_requests_changes(self):
        from core.verification.policy import decide

        rec, reason = decide(
            [
                {
                    "file": LOADER,
                    "title": "empty source_job_id accepted",
                    "claim": "empty source_job_id accepted",
                    "severity": "medium",
                    "kind": "defect",
                    "verify_status": "verified",
                    "existing_code": "if not source_job_id and not source_trial_ids:",
                    "invariant": "a source selector is required",
                    "violating_condition": "both fields empty",
                    "confidence": 0.8,
                }
            ],
            classification="source",
            files_changed=[LOADER],
        )
        self.assertEqual(rec, "REQUEST_CHANGES")
        self.assertEqual(reason, "verified_medium")

    def test_low_coverage_zero_findings_not_request_changes(self):
        from core.verification.policy import decide

        rec, reason = decide(
            [],
            classification="source",
            coverage={"units_total": 20, "units_packed": 4, "source_units": 18},
            files_changed=[LOADER],
        )
        self.assertNotEqual(rec, "REQUEST_CHANGES")
        self.assertNotIn("coverage", reason)
        self.assertEqual(rec, "MERGE")
        self.assertEqual(reason, "no_findings")


class TestChangelogCannotBlock(unittest.TestCase):
    def test_eight_restated_test_names_not_request_changes(self):
        from core.verification.policy import decide

        findings = []
        for i in range(8):
            findings.append(
                {
                    "file": "tests/test_foo.py",
                    "title": f"Test Foo case {i}",
                    "claim": f"test foo case {i}",
                    "severity": "medium",
                    "verification_status": "supported",
                    "kind": "note",
                }
            )
        rec, reason = decide(
            findings,
            classification="source",
            coverage={
                "units_total": 4,
                "units_packed": 4,
                "source_units": 2,
            },
            files_changed=["pkg/foo.py", "tests/test_foo.py"],
        )
        self.assertNotEqual(rec, "REQUEST_CHANGES")
        self.assertNotEqual(reason, "supported_medium")


if __name__ == "__main__":
    unittest.main(verbosity=2)
