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
from core.verification.loop import verify_findings_node
from core.verification.policy import recommendation_from_verification
from core.investigation.loop import run_investigation
from core.pr_facts import build_pr_facts

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


class TestVerifyNodeAndPolicy(unittest.TestCase):
    def test_stamps_every_keep_finding(self):
        findings = [
            {
                "id": "a",
                "file": SANITIZER,
                "symbol": "SQLIdentifierQuoter",
                "title": "quoter",
                "severity": "concern",
                "category": "correctness",
            },
            {
                "id": "b",
                "file": PIPELINE,
                "title": "ghost",
                "claim": "pipeline documentation",
                "severity": "high",
                "category": "code_quality",
            },
        ]
        state = {
            "validated_findings": findings,
            "findings": findings,
            "full_diff": FIXTURE_A,
            "files_changed": [SANITIZER],
            "pr_facts": {"files_changed": [SANITIZER], "classification": "source"},
            "pr_understanding": {"risk_level": "low"},
        }
        out = verify_findings_node(state)
        recs = out["verification_report"]["records"]
        self.assertEqual(len(recs), 2)
        by_id = {r["finding_id"]: r["status"] for r in recs}
        self.assertEqual(by_id["a"], "supported")
        self.assertEqual(by_id["b"], "unsupported")
        # unsupported cannot stay blocking-grade
        uns = [f for f in out["validated_findings"] if f["id"] == "b"][0]
        self.assertEqual(uns["severity"], "nit")
        self.assertEqual(out["verification_report"]["suggested_recommendation"], "REQUEST_CHANGES")

    def test_unsupported_cannot_solely_request_changes(self):
        findings = [
            {
                "verification_status": "unsupported",
                "severity": "high",
                "file": PIPELINE,
            }
        ]
        rec = recommendation_from_verification(findings, classification="source", risk="low")
        self.assertNotEqual(rec, "REQUEST_CHANGES")

    def test_supported_medium_is_request_changes_on_source(self):
        findings = [
            {
                "verification_status": "supported",
                "severity": "concern",
                "file": SANITIZER,
            }
        ]
        rec = recommendation_from_verification(findings, classification="source")
        self.assertEqual(rec, "REQUEST_CHANGES")

    def test_final_cannot_escalate_past_policy(self):
        from core.agents import final_recommender
        from core.models import ReviewOutput
        from unittest.mock import patch

        def fake_gen(**kwargs):
            return ReviewOutput(
                summary="lockfile looks risky",
                recommendation="REQUEST_CHANGES",
                confidence=0.9,
            )

        state = {
            "validated_findings": [
                {
                    "title": "Dependency Update",
                    "file": LOCK,
                    "evidence": [LOCK],
                    "severity": "concern",
                    "verification_status": "supported",
                }
            ],
            "pr_facts": {"classification": "lockfile-only"},
            "pr_understanding": {"summary": "lockfile", "risk_level": "low"},
            "review_plan": {"risk_level": "low"},
            "verification_report": {"ran": True, "suggested_recommendation": "COMMENT"},
        }
        with patch("core.agents.gateway") as gw:
            gw.generate_structured.side_effect = fake_gen
            out = final_recommender(state)
        self.assertEqual(out["recommendation"], "COMMENT")

    def test_lockfile_supported_is_comment_not_request_changes(self):
        findings = [
            {
                "verification_status": "supported",
                "severity": "concern",
                "file": LOCK,
            }
        ]
        rec = recommendation_from_verification(
            findings, classification="lockfile-only", risk="low"
        )
        self.assertEqual(rec, "COMMENT")

    def test_graph_order(self):
        from core.graph import build_review_graph

        g = build_review_graph()
        nodes = set(g.get_graph().nodes)
        self.assertIn("verify_findings", nodes)
        self.assertIn("investigate", nodes)

    def test_lockfile_investigate_skip_then_verify_runs(self):
        class Boom:
            def get_node(self, *a, **k):
                raise AssertionError("no hop")

            get_neighbors = get_node
            query = get_node
            get_pr_impact = get_node

        finding = {
            "id": "f-1",
            "title": "New Version of @swc/core",
            "claim": "updates @swc/core",
            "file": LOCK,
            "evidence": [LOCK],
        }
        facts = build_pr_facts(files_changed=[LOCK], full_diff=FIXTURE_B)
        state = {
            "repo": "FalkorDB/QueryWeaver",
            "number": 571,
            "files_changed": [LOCK],
            "full_diff": FIXTURE_B,
            "pr_facts": facts,
            "validated_findings": [finding],
            "findings": [finding],
            "review_plan": {},
        }
        inv = run_investigation(state, Boom())
        self.assertTrue(inv["investigation_report"]["skipped"])
        state.update(inv)
        out = verify_findings_node(state)
        self.assertEqual(out["verification_report"]["supported"], 1)
        self.assertEqual(out["validated_findings"][0]["verification_status"], "supported")

    def test_related_tests_heuristic(self):
        from core.verification.test_map import related_test_paths

        hits = related_test_paths(
            SANITIZER,
            [SANITIZER, "tests/test_sql_sanitizer.py", "README.md"],
        )
        self.assertIn("tests/test_sql_sanitizer.py", hits)


if __name__ == "__main__":
    unittest.main(verbosity=2)
