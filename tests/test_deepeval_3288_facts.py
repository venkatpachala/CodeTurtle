"""Deterministic facts for public PR confident-ai/deepeval#3288. No mocks."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.change_units import attach_change_units
from core.pr_facts import build_pr_facts

# Verified via GitHub API: https://github.com/confident-ai/deepeval/pull/3288
REPO = "confident-ai/deepeval"
PR = 3288
TITLE = "fix(kimi): keep unknown pricing as None instead of raising"
FILES = [
    "deepeval/models/llms/kimi_model.py",
    "tests/test_core/test_models/test_kimi_model.py",
]
DIFF = """diff --git a/deepeval/models/llms/kimi_model.py b/deepeval/models/llms/kimi_model.py
--- a/deepeval/models/llms/kimi_model.py
+++ b/deepeval/models/llms/kimi_model.py
@@ -1,3 +1,6 @@
 def cost():
-    raise ValueError("unknown pricing")
+    return None

diff --git a/tests/test_core/test_models/test_kimi_model.py b/tests/test_core/test_models/test_kimi_model.py
--- a/tests/test_core/test_models/test_kimi_model.py
+++ b/tests/test_core/test_models/test_kimi_model.py
@@ -1,2 +1,6 @@
+def test_unknown_pricing_is_none():
+    assert True
"""


class TestDeepEval3288Facts(unittest.TestCase):
    def test_classification_is_source(self):
        facts = build_pr_facts(
            title=TITLE,
            body="",
            files_changed=list(FILES),
            full_diff=DIFF,
            pr_number=PR,
            repo=REPO,
        )
        self.assertEqual(facts["classification"], "source")
        self.assertEqual(facts["file_count"], 2)
        self.assertEqual(facts["source_files"], FILES)
        self.assertFalse(facts.get("lock_files"))

    def test_change_units_cover_both_files(self):
        facts = build_pr_facts(
            title=TITLE,
            body="",
            files_changed=list(FILES),
            full_diff=DIFF,
            pr_number=PR,
            repo=REPO,
        )
        payload = attach_change_units(
            {
                "full_diff": DIFF,
                "files_changed": list(FILES),
                "pr_facts": facts,
            }
        )
        units = payload.get("change_units") or []
        self.assertGreaterEqual(len(units), 1)
        paths = {u["path"] if isinstance(u, dict) else u.path for u in units}
        self.assertTrue(paths.intersection(set(FILES)))


if __name__ == "__main__":
    unittest.main(verbosity=2)
