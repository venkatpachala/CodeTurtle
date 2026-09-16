"""V4.4 — RuleEngine. Synthetic paths. Ruff mocked."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.rules.engine import run_rule_engine
from core.runtime.models import Bundle

LOADER = "pkg/api/loader.py"


def _bundle(excerpt: str) -> Bundle:
    return Bundle(
        id="B-001",
        paths=[LOADER],
        units=[
            {
                "id": "CU-001",
                "path": LOADER,
                "excerpt": excerpt,
                "start_line": 4,
                "symbols": ["load"],
                "kind": "source",
            }
        ],
        symbols=["load"],
        kind="source",
    )


class TestRegexRules(unittest.TestCase):
    def test_eval_call(self):
        b = _bundle("+def load():\n+    return eval(user)\n")
        with patch("core.rules.engine.shutil.which", return_value=None):
            cands = run_rule_engine([b], files_changed=[LOADER])
        self.assertTrue(any("eval" in (c.title + c.claim).lower() for c in cands))
        self.assertTrue(all(c.source == "rule" for c in cands))
        self.assertEqual(cands[0].file, LOADER)

    def test_bare_except(self):
        b = _bundle("+try:\n+    load()\n+except:\n+    pass\n")
        with patch("core.rules.engine.shutil.which", return_value=None):
            cands = run_rule_engine([b], files_changed=[LOADER])
        self.assertTrue(any("except" in (c.title + c.claim).lower() for c in cands))

    def test_clean_hunk_no_regex_hit(self):
        b = _bundle("+def load():\n+    return 1\n")
        with patch("core.rules.engine.shutil.which", return_value=None):
            cands = run_rule_engine([b], files_changed=[LOADER])
        self.assertEqual(cands, [])


class TestRuffOptional(unittest.TestCase):
    def test_skip_when_ruff_missing(self):
        b = _bundle("+def load():\n+    return 1\n")
        with patch("core.rules.engine.shutil.which", return_value=None):
            cands = run_rule_engine([b], files_changed=[LOADER], repo_dir=".")
        self.assertEqual(cands, [])

    def test_ruff_json_becomes_rule_candidate(self):
        b = _bundle("+def load():\n+    return 1\n")
        payload = [
            {
                "filename": LOADER,
                "code": "E702",
                "message": "multiple statements on one line",
                "location": {"row": 4},
            }
        ]

        class Proc:
            stdout = json.dumps(payload)
            returncode = 1

        with patch("core.rules.engine.shutil.which", return_value="ruff"), patch(
            "core.rules.engine.subprocess.run", return_value=Proc()
        ), patch("core.rules.engine.Path.is_file", return_value=True):
            cands = run_rule_engine(
                [b], files_changed=[LOADER], repo_dir="."
            )
        self.assertTrue(cands)
        self.assertEqual(cands[0].source, "rule")
        self.assertEqual(cands[0].file, LOADER)
        self.assertIn("E702", cands[0].title)


if __name__ == "__main__":
    unittest.main(verbosity=2)
