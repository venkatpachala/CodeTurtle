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
            }
        ],
        "findings": [
            {
                "file": LOADER,
                "title": "nil deref in load",
                "severity": "medium",
                "verification_status": "supported",
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
