"""Phase 4.2 — related test path mapping. No execution."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.verification.hunk_verifier import verify_findings
from core.verification.policy import (
    adjust_testing_nit,
    recommendation_from_verification,
)
from core.verification.test_map import annotate_tests, related_test_paths

SANITIZER = "api/sql_utils/sql_sanitizer.py"
LOCK = "package-lock.json"

FIXTURE_A = f"""diff --git a/{SANITIZER} b/{SANITIZER}
--- a/{SANITIZER}
+++ b/{SANITIZER}
@@ -1,3 +1,8 @@
+class SQLIdentifierQuoter:
+    def quote(self, name):
+        return name
"""


class TestRelatedTestPaths(unittest.TestCase):
    def test_classic_pytest(self):
        hits = related_test_paths("api/foo.py", ["api/foo.py", "tests/test_foo.py"])
        self.assertEqual(hits, ["tests/test_foo.py"])
        d = annotate_tests({"file": "api/foo.py"}, ["api/foo.py", "tests/test_foo.py"])
        self.assertTrue(d["tests_touched"])
        self.assertEqual(d["related_tests"], ["tests/test_foo.py"])

    def test_colocated(self):
        d = annotate_tests({"file": "pkg/bar.py"}, ["pkg/bar.py", "pkg/test_bar.py"])
        self.assertTrue(d["tests_touched"])
        self.assertEqual(d["related_tests"], ["pkg/test_bar.py"])

    def test_js_spec(self):
        d = annotate_tests(
            {"file": "app/src/Modal.tsx"},
            ["app/src/Modal.tsx", "app/src/Modal.test.tsx"],
        )
        self.assertTrue(d["tests_touched"])
        self.assertEqual(d["related_tests"], ["app/src/Modal.test.tsx"])

    def test_no_test_in_pr(self):
        d = annotate_tests({"file": "api/foo.py"}, ["api/foo.py"])
        self.assertFalse(d["tests_touched"])
        self.assertEqual(d["related_tests"], [])

    def test_finding_is_the_test_file(self):
        d = annotate_tests(
            {"file": "tests/test_foo.py"},
            ["tests/test_foo.py"],
        )
        self.assertFalse(d["tests_touched"])
        self.assertEqual(d["related_tests"], [])

    def test_lockfile(self):
        d = annotate_tests({"file": LOCK}, [LOCK, "tests/test_lock.py"])
        self.assertFalse(d["tests_touched"])
        self.assertEqual(d["related_tests"], [])

    def test_unrelated_test(self):
        d = annotate_tests(
            {"file": "api/foo.py"},
            ["api/foo.py", "tests/test_other.py"],
        )
        self.assertFalse(d["tests_touched"])
        self.assertEqual(d["related_tests"], [])

    def test_neighbor_test_not_in_pr(self):
        d = annotate_tests(
            {
                "file": "api/foo.py",
                "reasoning": "see tests/test_foo.py",
            },
            ["api/foo.py"],
            neighbor_paths=["tests/test_foo.py"],
        )
        self.assertFalse(d["tests_touched"])
        self.assertEqual(d["related_tests"], [])

    def test_neighbor_test_in_pr(self):
        d = annotate_tests(
            {
                "file": "api/foo.py",
                "investigation_snippets": ["Neighbors: tests/test_foo.py"],
            },
            ["api/foo.py", "tests/test_foo.py"],
        )
        self.assertTrue(d["tests_touched"])
        self.assertIn("tests/test_foo.py", d["related_tests"])


class TestStatusUnchanged(unittest.TestCase):
    def test_hunk_status_not_flipped_by_tests_touched(self):
        findings = [
            {
                "id": "a",
                "file": SANITIZER,
                "symbol": "SQLIdentifierQuoter",
                "title": "add tests for sanitizer",
                "claim": "missing tests for SQLIdentifierQuoter",
                "severity": "concern",
            }
        ]
        stamped, recs = verify_findings(
            findings,
            FIXTURE_A,
            files_changed=[SANITIZER, "tests/test_sql_sanitizer.py"],
        )
        self.assertEqual(stamped[0]["verification_status"], "supported")
        self.assertEqual(recs[0].status, "supported")
        self.assertTrue(stamped[0]["tests_touched"])
        self.assertIn("tests/test_sql_sanitizer.py", stamped[0]["related_tests"])
        # testing-nit downgrade only
        self.assertEqual(stamped[0]["severity"], "nit")


class TestPolicyWithTests(unittest.TestCase):
    def test_add_tests_uncertain_still_not_request_changes(self):
        finding = {
            "title": "add tests for sanitizer",
            "claim": "missing test coverage",
            "file": SANITIZER,
            "severity": "concern",
            "verification_status": "uncertain",
            "tests_touched": False,
        }
        rec = recommendation_from_verification(
            [finding], classification="source", risk="medium"
        )
        self.assertNotEqual(rec, "REQUEST_CHANGES")
        rec2 = recommendation_from_verification(
            [adjust_testing_nit(dict(finding), tests_touched=True)],
            classification="source",
            risk="medium",
        )
        self.assertNotEqual(rec2, "REQUEST_CHANGES")

    def test_lockfile_comment_clamp_unchanged(self):
        rec = recommendation_from_verification(
            [
                {
                    "verification_status": "supported",
                    "severity": "concern",
                    "file": LOCK,
                    "tests_touched": False,
                }
            ],
            classification="lockfile-only",
            risk="low",
        )
        self.assertEqual(rec, "COMMENT")

    def test_unsupported_cannot_sole_request_changes(self):
        rec = recommendation_from_verification(
            [
                {
                    "verification_status": "unsupported",
                    "severity": "high",
                    "tests_touched": True,
                }
            ],
            classification="source",
        )
        self.assertNotEqual(rec, "REQUEST_CHANGES")


if __name__ == "__main__":
    unittest.main(verbosity=2)
