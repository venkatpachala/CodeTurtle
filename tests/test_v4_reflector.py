"""V4.3 — Positioner + Reflector. Synthetic DROP/KEEP."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.positioner import position_candidate
from core.reflector import reflect_candidate
from core.runtime.models import Candidate
from core.verification.diff_index import build_diff_index

LOADER = "pkg/api/loader.py"
TEST_LOADER = "tests/test_loader.py"
TEST_OTHER = "tests/test_other.py"
README = "README.md"

DIFF = (
    f"diff --git a/{LOADER} b/{LOADER}\n"
    f"--- a/{LOADER}\n"
    f"+++ b/{LOADER}\n"
    f"@@ -1,1 +1,8 @@\n"
    f" context\n"
    f"+def load():\n"
    f"+    cursor = connection.cursor()\n"
    f"+    return cursor\n"
    f"+def refresh_schema():\n"
    f"+    return True\n"
    f"diff --git a/{TEST_LOADER} b/{TEST_LOADER}\n"
    f"--- a/{TEST_LOADER}\n"
    f"+++ b/{TEST_LOADER}\n"
    f"@@ -1,1 +1,4 @@\n"
    f" context\n"
    f"+def test_load():\n"
    f"+    assert load()\n"
)

FILES = [LOADER, TEST_LOADER]


def _cand(**kwargs) -> Candidate:
    base = dict(
        bundle_id="B-001",
        file=LOADER,
        symbol="load",
        start_line=2,
        title="load cursor leak",
        claim="load opens a cursor without closing it",
        existing_code="cursor = connection.cursor()",
        invariant="cursor must be closed",
        violating_condition="cursor leaked",
        severity="medium",
        source="agent",
        evidence_paths=[LOADER],
    )
    base.update(kwargs)
    return Candidate(**base)


class TestPositioner(unittest.TestCase):
    def test_resolves_right_side_line(self):
        idx = build_diff_index(DIFF)
        line = position_candidate(_cand(), idx)
        self.assertIsNotNone(line)
        self.assertGreaterEqual(int(line), 1)

    def test_missing_file_has_no_line(self):
        idx = build_diff_index(DIFF)
        line = position_candidate(_cand(file="pkg/missing.py", symbol="nope"), idx)
        self.assertIsNone(line)


class TestReflector(unittest.TestCase):
    def setUp(self):
        self.idx = build_diff_index(DIFF)

    def test_drop_file_not_in_pr(self):
        keep, reason = reflect_candidate(
            _cand(file=README, evidence_paths=[README]),
            files_changed=FILES,
            index=self.idx,
            line=2,
        )
        self.assertFalse(keep)
        self.assertEqual(reason, "file_not_in_pr")

    def test_drop_test_for_on_nontest_file(self):
        keep, reason = reflect_candidate(
            _cand(title="Test for loader", file=LOADER),
            files_changed=FILES,
            index=self.idx,
            line=2,
        )
        self.assertFalse(keep)
        self.assertIn(reason, ("test_for_on_nontest", "changelog", "test_restatement"))

    def test_drop_evidence_not_in_pr(self):
        keep, reason = reflect_candidate(
            _cand(evidence_paths=["pkg/missing.py"]),
            files_changed=FILES,
            index=self.idx,
            line=2,
        )
        self.assertFalse(keep)
        self.assertEqual(reason, "evidence_not_in_pr")

    def test_drop_symbol_path(self):
        keep, reason = reflect_candidate(
            _cand(symbol="loader.py"),
            files_changed=FILES,
            index=self.idx,
            line=2,
        )
        self.assertFalse(keep)
        self.assertEqual(reason, "symbol_is_path")

    def test_drop_no_line(self):
        keep, reason = reflect_candidate(
            _cand(),
            files_changed=FILES,
            index=self.idx,
            line=None,
        )
        self.assertFalse(keep)
        self.assertEqual(reason, "no_line")

    def test_drop_stopword_only(self):
        keep, reason = reflect_candidate(
            _cand(
                symbol="",
                title="the file and data",
                claim="name value test code agent trial type config",
                evidence_paths=[LOADER],
            ),
            files_changed=FILES,
            index=self.idx,
            line=2,
        )
        self.assertFalse(keep)
        self.assertEqual(reason, "stopword_only")

    def test_keep_symbol_in_hunk(self):
        keep, reason = reflect_candidate(
            _cand(),
            files_changed=FILES,
            index=self.idx,
            line=2,
        )
        self.assertTrue(keep)
        self.assertEqual(reason, "symbol_in_hunk")

    def test_keep_distinctive_tokens(self):
        keep, reason = reflect_candidate(
            _cand(
                symbol="",
                title="cursor leak",
                claim="connection cursor is never closed",
                evidence_paths=[LOADER],
            ),
            files_changed=FILES,
            index=self.idx,
            line=2,
        )
        self.assertTrue(keep)
        self.assertEqual(reason, "token_overlap")

    def test_synthetic_drop_test_for_empty_input_other_test_not_in_pr(self):
        keep, reason = reflect_candidate(
            _cand(
                title="Test for Empty Input",
                file=LOADER,
                symbol="",
                evidence_paths=[TEST_OTHER],
            ),
            files_changed=FILES,
            index=self.idx,
            line=2,
        )
        self.assertFalse(keep)
        self.assertIn(
            reason,
            ("test_for_on_nontest", "evidence_not_in_pr", "changelog", "test_restatement"),
        )
        self.assertNotIn(TEST_OTHER, FILES)

    def test_synthetic_keep_refresh_schema_in_hunk(self):
        keep, reason = reflect_candidate(
            _cand(
                file=LOADER,
                symbol="refresh_schema",
                title="refresh_schema mutates graph",
                claim="refresh_schema is added in this hunk",
                evidence_paths=[LOADER],
            ),
            files_changed=FILES,
            index=self.idx,
            line=2,
        )
        self.assertTrue(keep)
        self.assertEqual(reason, "symbol_in_hunk")
        blob = "\n".join(
            (h.added or "") + (h.body or "") for h in self.idx.hunks_for(LOADER)
        )
        self.assertIn("refresh_schema", blob)
        self.assertEqual(LOADER, "pkg/api/loader.py")


if __name__ == "__main__":
    unittest.main(verbosity=2)
