"""Phase 7.5 — failure-path hyps from mutation ChangeUnits. No new LLM agent."""

from __future__ import annotations

import io
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.change_units import build_change_units
from core.failure_paths import (
    MAX_FAILURE_PATH_HYPS,
    extract_failure_paths,
    extract_failure_paths_node,
)
from core.hypothesis import KEEP, PLAUSIBLE, REJECTED, classify_hypothesis, classify_hypotheses_node
from core.investigation.planner import findings_to_hypotheses
from core.pr_facts import build_pr_facts

LOADER = "api/loaders/sqlserver_loader.py"
PIPELINE = "api/core/pipeline.py"
WORDLIST = ".github/wordlist.txt"
LOCK = "package-lock.json"

DIFF_MUT = f"""diff --git a/{LOADER} b/{LOADER}
--- a/{LOADER}
+++ b/{LOADER}
@@ -700,3 +700,12 @@ class SQLServerLoader:
     def load_schema(self):
         pass
+    def refresh_graph_schema(self):
+        self.graph.delete(node)
+        self.load()
+        return True
"""

DIFF_PRINT = f"""diff --git a/{PIPELINE} b/{PIPELINE}
--- a/{PIPELINE}
+++ b/{PIPELINE}
@@ -1,2 +1,4 @@
 def run():
+    print("hello")
     pass
"""

DIFF_LOCK = f"""diff --git a/{LOCK} b/{LOCK}
--- a/{LOCK}
+++ b/{LOCK}
@@ -1,2 +1,4 @@
 {{
+  "version": "1"
 }}
"""

DIFF_WORDLIST = f"""diff --git a/{WORDLIST} b/{WORDLIST}
--- a/{WORDLIST}
+++ b/{WORDLIST}
@@ -1,1 +1,2 @@
+foobar
"""


def _units(diff, files):
    return build_change_units(diff, files)


class TestExtract(unittest.TestCase):
    def test_graph_delete_then_load_emits_one(self):
        units = _units(DIFF_MUT, [LOADER])
        buf = io.StringIO()
        with redirect_stdout(buf):
            hyps = extract_failure_paths(units, files_changed=[LOADER])
        self.assertEqual(len(hyps), 1)
        h = hyps[0]
        self.assertEqual(h.file, LOADER)
        self.assertEqual(h.symbol, "refresh_graph_schema")
        self.assertIn("graph.delete", h.claim)
        self.assertIn("load", h.claim)
        self.assertEqual(h.mutation, "graph.delete")
        self.assertEqual(h.next_step, "load")
        self.assertTrue(h.start_line)
        log = buf.getvalue()
        self.assertIn("[FailurePaths] units_scanned=", log)
        self.assertIn("emitted=1", log)
        self.assertIn("graph.delete → load", log)

    def test_print_only_emits_zero(self):
        units = _units(DIFF_PRINT, [PIPELINE])
        hyps = extract_failure_paths(units, files_changed=[PIPELINE])
        self.assertEqual(hyps, [])

    def test_lockfile_unit_skip(self):
        units = _units(DIFF_LOCK, [LOCK])
        facts = build_pr_facts(files_changed=[LOCK], full_diff=DIFF_LOCK, title="lock")
        buf = io.StringIO()
        with redirect_stdout(buf):
            hyps = extract_failure_paths(
                units,
                files_changed=[LOCK],
                classification=str(facts.get("classification") or "lockfile-only"),
            )
        self.assertEqual(hyps, [])
        self.assertIn("skip", buf.getvalue().lower())

    def test_dedup_same_file_symbol_mutation(self):
        units = _units(DIFF_MUT, [LOADER])
        doubled = list(units) + list(units)
        hyps = extract_failure_paths(doubled, files_changed=[LOADER])
        self.assertEqual(len(hyps), 1)

    def test_four_mutation_units_cap_three(self):
        files = [
            "a.py",
            "b.py",
            "c.py",
            "d.py",
        ]
        parts = []
        for i, p in enumerate(files):
            parts.append(
                f"""diff --git a/{p} b/{p}
--- a/{p}
+++ b/{p}
@@ -1,1 +1,6 @@
+def fn_{i}():
+    self.graph.delete(x)
+    self.load()
"""
            )
        diff = "\n".join(parts)
        units = _units(diff, files)
        hyps = extract_failure_paths(units, files_changed=files)
        self.assertLessEqual(len(hyps), MAX_FAILURE_PATH_HYPS)
        self.assertEqual(len(hyps), 3)

    def test_wordlist_only_zero(self):
        units = _units(DIFF_WORDLIST, [WORDLIST])
        hyps = extract_failure_paths(units, files_changed=[WORDLIST])
        self.assertEqual(hyps, [])


class TestClassifyAndPlanner(unittest.TestCase):
    def test_file_in_pr_is_keep_or_plausible_not_rejected(self):
        units = _units(DIFF_MUT, [LOADER])
        hyps = extract_failure_paths(units, files_changed=[LOADER])
        finding = hyps[0].as_finding(1)
        status, _ = classify_hypothesis(
            finding, files_changed=[LOADER], full_diff=DIFF_MUT
        )
        self.assertIn(status, (KEEP, PLAUSIBLE))
        self.assertNotEqual(status, REJECTED)

    def test_failure_path_beats_naming_for_hops(self):
        units = _units(DIFF_MUT, [LOADER, PIPELINE])
        fp = extract_failure_paths(units, files_changed=[LOADER, PIPELINE])[0].as_finding(1)
        fp["hypothesis_status"] = KEEP
        naming = {
            "id": "n-1",
            "title": "Naming and Documentation",
            "claim": "rename helper",
            "file": PIPELINE,
            "evidence": [PIPELINE],
            "hypothesis_status": KEEP,
            "needs_investigation": True,
            "severity": "nit",
        }
        hyps = findings_to_hypotheses(
            [naming, fp],
            files_changed=[LOADER, PIPELINE],
            full_diff=DIFF_MUT,
        )
        self.assertTrue(hyps)
        self.assertEqual(hyps[0].finding_id, "fp-1")
        self.assertIn("graph.delete", hyps[0].claim)

    def test_classify_node_merges_failure_path_findings(self):
        units = _units(DIFF_MUT, [LOADER])
        fps = [h.as_finding(1) for h in extract_failure_paths(units, files_changed=[LOADER])]
        state = {
            "files_changed": [LOADER],
            "full_diff": DIFF_MUT,
            "pr_facts": build_pr_facts(
                files_changed=[LOADER], full_diff=DIFF_MUT, title="loader"
            ),
            "correctness_findings": [],
            "quality_findings": [],
            "testing_findings": [],
            "failure_path_findings": fps,
        }
        out = classify_hypotheses_node(state)
        pool = out["hypothesis_pool"]
        self.assertTrue(pool)
        self.assertTrue(any(f.get("failure_path") for f in pool))
        self.assertTrue(any(f.get("symbol") == "refresh_graph_schema" for f in pool))


class TestGraphAnd571(unittest.TestCase):
    def test_graph_extract_between_units_and_classify(self):
        from core.graph import build_review_graph

        g = build_review_graph()
        nodes = set(g.get_graph().nodes)
        self.assertIn("extract_failure_paths", nodes)
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
        self.assertIn(("classify_hypotheses", "investigate"), edges)

    def test_571_shaped_emitted_zero(self):
        facts = build_pr_facts(files_changed=[LOCK], full_diff=DIFF_LOCK, title="lock")
        self.assertEqual(facts.get("classification"), "lockfile-only")
        state = {
            "full_diff": DIFF_LOCK,
            "files_changed": [LOCK],
            "pr_facts": facts,
            "change_units": [u.model_dump() for u in _units(DIFF_LOCK, [LOCK])],
        }
        buf = io.StringIO()
        with redirect_stdout(buf):
            out = extract_failure_paths_node(state)
        self.assertEqual(out["failure_path_findings"], [])
        self.assertEqual(out["failure_path_report"]["emitted"], 0)
        self.assertTrue(out["failure_path_report"].get("skipped"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
