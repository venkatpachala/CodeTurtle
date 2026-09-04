"""Phase 7.2 — ChangeUnit hunks for specialists instead of a 14k full_diff slice."""

from __future__ import annotations

import io
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.agents import _build_specialist_context, _diff_for_review
from core.change_units import (
    build_change_units,
    format_units,
    attach_change_units,
    specialist_code_view,
)
from core.pr_facts import build_pr_facts
from core.verification.diff_index import build_diff_index
from core.verification.policy import recommendation_from_verification

LOADER = "api/loaders/sqlserver_loader.py"
PIPELINE = "api/core/pipeline.py"
TEST_FOO = "tests/test_foo.py"
LOCK = "package-lock.json"
README = "README.md"

OMITTED_TOKEN = "ZZZ_OMITTED_FULL_DIFF_TAIL_TOKEN"

DIFF_THREE = f"""diff --git a/{LOADER} b/{LOADER}
--- a/{LOADER}
+++ b/{LOADER}
@@ -1,3 +1,8 @@
 class SQLServerLoader:
     def load_schema(self):
         pass
+    def refresh_graph_schema(self):
+        self.graph.delete(node)
+        return True
@@ -80,2 +90,6 @@
     def connect(self):
+        cursor = self.connection.cursor()
+        return cursor
         pass
diff --git a/{PIPELINE} b/{PIPELINE}
--- a/{PIPELINE}
+++ b/{PIPELINE}
@@ -10,3 +10,7 @@
 def run():
+    return load()
     pass
"""

DIFF_TEST = f"""diff --git a/{TEST_FOO} b/{TEST_FOO}
--- a/{TEST_FOO}
+++ b/{TEST_FOO}
@@ -1,1 +1,4 @@
+def test_foo():
+    assert True
 context
"""

DIFF_LOCK = f"""diff --git a/{LOCK} b/{LOCK}
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

PADDING = "x" * 400
DIFF_LARGE = f"""diff --git a/{LOADER} b/{LOADER}
--- a/{LOADER}
+++ b/{LOADER}
@@ -1,2 +1,6 @@
 class SQLServerLoader:
+    def refresh_graph_schema(self):
+        self.graph.delete(node)
+        return True
 context
diff --git a/{PIPELINE} b/{PIPELINE}
--- a/{PIPELINE}
+++ b/{PIPELINE}
@@ -1,1 +1,8 @@
+def run():
+    # {OMITTED_TOKEN}
+    a = "{PADDING}"
+    b = "{PADDING}"
+    c = "{PADDING}"
+    return a
 context
diff --git a/{README} b/{README}
--- a/{README}
+++ b/{README}
@@ -1,1 +1,4 @@
+# docs
+{OMITTED_TOKEN}
 context
"""


class TestBuildChangeUnits(unittest.TestCase):
    def test_unified_diff_two_files_three_hunks(self):
        files = [LOADER, PIPELINE]
        buf = io.StringIO()
        with redirect_stdout(buf):
            units = build_change_units(DIFF_THREE, files)
        self.assertEqual(len(units), 3)
        self.assertEqual([u.id for u in units], ["CU-001", "CU-002", "CU-003"])
        self.assertEqual(units[0].path, LOADER)
        self.assertEqual(units[0].start_line, 1)
        self.assertEqual(units[0].end_line, 8)
        self.assertEqual(units[1].path, LOADER)
        self.assertEqual(units[1].start_line, 90)
        self.assertEqual(units[2].path, PIPELINE)
        idx = build_diff_index(DIFF_THREE)
        h0 = idx.hunks_for(LOADER)[0]
        self.assertEqual(units[0].start_line, h0.new_start)
        self.assertEqual(units[0].end_line, h0.new_end)
        self.assertIn("refresh_graph_schema", units[0].symbols)
        log = buf.getvalue()
        self.assertIn("[ChangeUnits] n=3 source=3", log)
        self.assertIn("CU-001", log)
        self.assertIn(LOADER, log)

    def test_graph_delete_is_mutation(self):
        units = build_change_units(DIFF_THREE, [LOADER, PIPELINE])
        mut = [u for u in units if "graph.delete" in (u.excerpt or "")]
        self.assertTrue(mut)
        self.assertEqual(mut[0].risk_hint, "mutation")
        self.assertEqual(mut[0].kind, "source")

    def test_test_foo_kind_test(self):
        units = build_change_units(DIFF_TEST, [TEST_FOO])
        self.assertEqual(len(units), 1)
        self.assertEqual(units[0].kind, "test")
        self.assertEqual(units[0].path, TEST_FOO)
        self.assertEqual(units[0].risk_hint, "test")

    def test_package_lock_kind_lockfile(self):
        units = build_change_units(DIFF_LOCK, [LOCK])
        self.assertGreaterEqual(len(units), 1)
        self.assertEqual(units[0].kind, "lockfile")
        self.assertEqual(units[0].path, LOCK)

    def test_empty_diff_n_zero(self):
        units = build_change_units("", [])
        self.assertEqual(units, [])
        packed, cov = format_units(units)
        self.assertEqual(cov["units_total"], 0)
        self.assertEqual(cov["units_packed"], 0)
        self.assertIn("no change units", packed)

    def test_skip_empty_hunk(self):
        diff = f"""diff --git a/{PIPELINE} b/{PIPELINE}
--- a/{PIPELINE}
+++ b/{PIPELINE}
@@ -1,1 +1,1 @@
 context only
"""
        units = build_change_units(diff, [PIPELINE])
        self.assertEqual(units, [])

    def test_hunk_raw_and_new_end_exposed(self):
        idx = build_diff_index(DIFF_THREE)
        h = idx.hunks_for(LOADER)[0]
        self.assertTrue(h.raw.startswith("@@"))
        self.assertIn("refresh_graph_schema", h.raw)
        self.assertEqual(h.new_end, h.new_start + h.new_count - 1)


class TestFormatUnits(unittest.TestCase):
    def test_max_chars_omits_and_mutation_first(self):
        units = build_change_units(DIFF_LARGE, [LOADER, PIPELINE, README])
        self.assertGreaterEqual(len(units), 2)
        packed, cov = format_units(units, max_chars=500)
        self.assertGreaterEqual(cov["units_omitted"], 1)
        self.assertGreaterEqual(cov["units_packed"], 1)
        self.assertIn("CU-001", packed)
        self.assertIn("graph.delete", packed)
        self.assertIn("mutation", packed)
        # docs skipped on mixed PR; omitted hunk token must not appear
        self.assertNotIn(OMITTED_TOKEN, packed)
        first_cu = packed.find("### CU-")
        self.assertGreaterEqual(first_cu, 0)
        self.assertIn("sqlserver_loader.py", packed[first_cu : first_cu + 80])

    def test_lockfile_only_packs_lockfile_unit(self):
        units = build_change_units(DIFF_LOCK, [LOCK])
        packed, cov = format_units(units, max_chars=2000, lockfile_only=True)
        self.assertGreaterEqual(cov["units_packed"], 1)
        self.assertIn(LOCK, packed)
        self.assertIn("CU-001", packed)

    def test_mixed_skips_lockfile_and_docs(self):
        diff = DIFF_THREE + "\n" + DIFF_LOCK + "\n" + f"""diff --git a/{README} b/{README}
--- a/{README}
+++ b/{README}
@@ -1,1 +1,3 @@
+# hi
 context
"""
        files = [LOADER, PIPELINE, LOCK, README]
        units = build_change_units(diff, files)
        packed, cov = format_units(units, max_chars=12000, lockfile_only=False)
        self.assertNotIn(LOCK, packed)
        self.assertNotIn("README.md:", packed)
        self.assertGreater(cov["source_units"], 0)
        self.assertEqual(cov["units_packed"] + cov["units_omitted"], cov["units_total"])


class TestSpecialistPayload(unittest.TestCase):
    def test_no_raw_full_diff_when_units_exist(self):
        files = [LOADER, PIPELINE, README]
        facts = build_pr_facts(
            title="loader",
            files_changed=files,
            full_diff=DIFF_LARGE,
        )
        state = {
            "title": "SQL Server loader",
            "body": "refresh schema",
            "full_diff": DIFF_LARGE,
            "files_changed": files,
            "pr_facts": facts,
        }
        attached = attach_change_units(state, max_chars=500)
        state.update(attached)
        view = _diff_for_review(state, max_chars=14000)
        self.assertIn("### CU-", view)
        self.assertNotIn(OMITTED_TOKEN, view)
        # Must not be a raw unified-diff prefix
        self.assertFalse(view.lstrip().startswith("diff --git"))
        block = _build_specialist_context(
            state,
            role_focus="CORRECTNESS",
            max_diff_chars=14000,
            max_evidence_chunks=2,
        )
        self.assertIn("CHANGE UNITS", block)
        self.assertIn("### CU-", block)
        self.assertNotIn(OMITTED_TOKEN, block)
        self.assertIn("Cite `file` and `start_line`", _shared_rules_snippet())

    def test_specialist_code_view_helper(self):
        state = {
            "full_diff": DIFF_THREE,
            "files_changed": [LOADER, PIPELINE],
            "pr_facts": {"classification": "source", "files_changed": [LOADER, PIPELINE]},
        }
        view = specialist_code_view(state, max_chars=12000)
        self.assertIn("### CU-001", view)
        self.assertIn(LOADER, view)
        self.assertIn("refresh_graph_schema", view)

    def test_attach_sets_coverage_not_merge_policy(self):
        state = {
            "full_diff": DIFF_THREE,
            "files_changed": [LOADER, PIPELINE],
            "pr_facts": {"classification": "source", "files_changed": [LOADER, PIPELINE]},
        }
        out = attach_change_units(state)
        cov = out["review_coverage"]
        self.assertEqual(cov["units_total"], 3)
        self.assertEqual(cov["source_units"], 3)
        self.assertIn("units_packed", cov)
        rec = recommendation_from_verification(
            [], classification="source", risk="medium"
        )
        # 7.2 must not change MERGE policy
        self.assertEqual(rec, "COMMENT")


class TestGraphAndLockfileEvalShape(unittest.TestCase):
    def test_graph_has_change_units_before_understanding(self):
        from core.graph import build_review_graph

        g = build_review_graph()
        nodes = set(g.get_graph().nodes)
        self.assertIn("change_units", nodes)
        edges = set()
        for e in g.get_graph().edges:
            src = getattr(e, "source", None)
            tgt = getattr(e, "target", None)
            if src is None and isinstance(e, (tuple, list)) and len(e) >= 2:
                src, tgt = e[0], e[1]
            if src and tgt:
                edges.add((str(src), str(tgt)))
        self.assertIn(("change_units", "extract_failure_paths"), edges)
        self.assertIn(("extract_failure_paths", "pr_understanding"), edges)

    def test_571_shaped_lockfile_has_unit(self):
        facts = build_pr_facts(files_changed=[LOCK], full_diff=DIFF_LOCK, title="lock")
        self.assertEqual(facts.get("classification"), "lockfile-only")
        state = {
            "full_diff": DIFF_LOCK,
            "files_changed": [LOCK],
            "pr_facts": facts,
        }
        out = attach_change_units(state)
        kinds = {u["kind"] for u in out["change_units"]}
        self.assertIn("lockfile", kinds)
        self.assertGreaterEqual(len(out["change_units"]), 1)
        self.assertIn(LOCK, out["review_diff"])


def _shared_rules_snippet() -> str:
    from core.agents import _SHARED_SYSTEM_RULES, _CORRECTNESS_ROLE_FOCUS

    return _SHARED_SYSTEM_RULES + _CORRECTNESS_ROLE_FOCUS


if __name__ == "__main__":
    unittest.main(verbosity=2)
