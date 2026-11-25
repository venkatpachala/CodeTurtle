"""Phase 4.1 — hunk-level claim verification. KEEP ≠ proven."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.verification.diff_index import build_diff_index
from core.verification.hunk_verifier import verify_finding, verify_findings

SANITIZER = "api/sql_utils/sql_sanitizer.py"
PIPELINE = "api/core/pipeline.py"
LOCK = "package-lock.json"

FIXTURE_A = f"""diff --git a/{SANITIZER} b/{SANITIZER}
--- a/{SANITIZER}
+++ b/{SANITIZER}
@@ -1,3 +1,8 @@
+class SQLIdentifierQuoter:
+    def quote(self, name):
+        return name
 context
"""

FIXTURE_B = f"""diff --git a/{LOCK} b/{LOCK}
--- a/{LOCK}
+++ b/{LOCK}
@@ -10,4 +10,8 @@
   "packages": {{
+    "node_modules/@swc/core": {{
+      "version": "1.15.33",
+      "engines": {{ "node": ">=20.19.0" }}
+    }}
   }}
"""

FIXTURE_C = f"""diff --git a/{SANITIZER} b/{SANITIZER}
--- a/{SANITIZER}
+++ b/{SANITIZER}
@@ -40,2 +40,10 @@ class SQLIdentifierQuoter:
     def quote(self, name):
+        if not name:
+            return ""
         return name
"""


class TestDiffIndex(unittest.TestCase):
    def test_parses_files_and_hunks(self):
        idx = build_diff_index(FIXTURE_A)
        self.assertIn(SANITIZER, idx.files)
        hunks = idx.hunks_for(SANITIZER)
        self.assertEqual(len(hunks), 1)
        self.assertIn("SQLIdentifierQuoter", hunks[0].added)
        self.assertTrue(idx.contains(SANITIZER, "SQLIdentifierQuoter"))
        self.assertTrue(idx.line_in_new_file(SANITIZER, 2))
        self.assertFalse(idx.line_in_new_file(SANITIZER, 900))

    def test_basename_lookup(self):
        idx = build_diff_index(FIXTURE_A)
        self.assertTrue(idx.hunks_for("sql_sanitizer.py"))


class TestHunkVerifierSource(unittest.TestCase):
    def test_symbol_supported(self):
        idx = build_diff_index(FIXTURE_A)
        rec = verify_finding(
            {"file": SANITIZER, "symbol": "SQLIdentifierQuoter", "title": "quoter"},
            idx,
        )
        self.assertEqual(rec.status, "supported")
        self.assertIn("symbol_in_hunk", rec.reasons)

    def test_documentation_claim_uncertain(self):
        idx = build_diff_index(FIXTURE_A)
        rec = verify_finding(
            {
                "file": SANITIZER,
                "title": "add documentation",
                "claim": "please add documentation comments",
            },
            idx,
        )
        self.assertEqual(rec.status, "uncertain")
        self.assertIn("no_token_in_hunk", rec.reasons)

    def test_file_not_in_diff_unsupported(self):
        idx = build_diff_index(FIXTURE_A)
        rec = verify_finding(
            {"file": PIPELINE, "title": "pipeline bug", "claim": "pipeline is wrong"},
            idx,
        )
        self.assertEqual(rec.status, "unsupported")
        self.assertIn("no_hunk_for_file", rec.reasons)

    def test_line_range_supported(self):
        idx = build_diff_index(FIXTURE_C)
        rec = verify_finding(
            {"file": SANITIZER, "start_line": 42, "title": "empty name"},
            idx,
        )
        self.assertEqual(rec.status, "supported")
        self.assertIn("line_in_hunk", rec.reasons)

    def test_line_out_of_range_falls_through(self):
        idx = build_diff_index(FIXTURE_C)
        rec = verify_finding(
            {
                "file": SANITIZER,
                "start_line": 900,
                "title": "add documentation",
                "claim": "please add documentation",
            },
            idx,
        )
        self.assertNotEqual(rec.status, "supported")
        self.assertIn(rec.status, ("uncertain", "unsupported"))


class TestHunkVerifierLockfile(unittest.TestCase):
    def test_swc_core_supported(self):
        idx = build_diff_index(FIXTURE_B)
        rec = verify_finding(
            {
                "file": LOCK,
                "title": "New Version of @swc/core",
                "claim": "updates @swc/core in the lockfile",
            },
            idx,
        )
        self.assertEqual(rec.status, "supported")
        self.assertTrue(any("swc" in t.lower() or t.startswith("@") for t in rec.matched_tokens))

    def test_node_version_supported(self):
        idx = build_diff_index(FIXTURE_B)
        rec = verify_finding(
            {
                "file": LOCK,
                "title": "Engines Requirement",
                "claim": "requires Node 20.19.0 or higher",
            },
            idx,
        )
        self.assertEqual(rec.status, "supported")

    def test_arm64_feature_not_supported(self):
        idx = build_diff_index(FIXTURE_B)
        rec = verify_finding(
            {
                "file": LOCK,
                "title": "ARM64 architecture feature",
                "claim": "add ARM64 architecture feature support",
            },
            idx,
        )
        self.assertIn(rec.status, ("uncertain", "unsupported"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
