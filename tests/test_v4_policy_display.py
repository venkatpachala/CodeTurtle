"""V4.0 — Policy owns Decision. REQUEST_CHANGES must not display as MERGE."""

from __future__ import annotations

import re
import sys
import unittest
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from rich.console import Console

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from cli.commands.review import ReviewPipeline
from core.github_review import clamped_decision, github_event

LOADER = "pkg/api/loader.py"


def _blocking_state():
    return {
        "recommendation": "MERGE",
        "final_comment": "Looks good to merge. No issues.",
        "merge_decision": {
            "recommendation": "MERGE",
            "summary": "MERGE",
            "policy_reason": "",
        },
        "validated_findings": [
            {
                "file": LOADER,
                "title": "nil deref in load",
                "claim": "load() dereferences a missing cursor",
                "severity": "medium",
                "verification_status": "supported",
                "verify_status": "verified",
                "kind": "defect",
                "existing_code": "cursor = connection.cursor()",
                "invariant": "cursor must exist",
                "violating_condition": "connection is None",
            }
        ],
        "findings": [
            {
                "file": LOADER,
                "title": "nil deref in load",
                "severity": "medium",
                "verification_status": "supported",
                "verify_status": "verified",
                "kind": "defect",
            }
        ],
        "pr_facts": {
            "classification": "source",
            "files_changed": [LOADER],
            "source_files": [LOADER],
        },
        "files_changed": [LOADER],
        "review_coverage": {
            "units_total": 2,
            "units_packed": 2,
            "units_omitted": 0,
            "source_units": 2,
        },
        "policy_reason": "",
    }


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
        self.assertEqual(rec, "COMMENT")
        self.assertNotEqual(reason, "supported_medium")
        self.assertNotIn("coverage", reason)
        self.assertEqual(reason, "uncertain_only")

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


class TestPolicyOwnsDisplay(unittest.TestCase):
    def test_clamped_decision_is_request_changes(self):
        rec = clamped_decision(_blocking_state())
        self.assertEqual(rec, "REQUEST_CHANGES")
        self.assertEqual(github_event(rec, "source"), "REQUEST_CHANGES")

    def test_display_prints_policy_not_leftover_merge(self):
        pipe = ReviewPipeline()
        pipe.context.final_state = _blocking_state()
        buf = StringIO()
        fake = Console(file=buf, width=140, color_system=None, highlight=False)
        with patch("cli.commands.review.console", fake):
            pipe._display_results()
        text = buf.getvalue()
        self.assertRegex(text, r"Decision:\s*REQUEST_CHANGES")
        self.assertIsNone(re.search(r"Decision:\s*MERGE", text))


if __name__ == "__main__":
    unittest.main(verbosity=2)
