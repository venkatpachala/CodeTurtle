"""Unit tests for Phase 5.1 gate scorer. Hand-built snapshots, no network."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.evaluation.snapshot import ReviewSnapshot, from_state
from tests.evaluation.schema import GoldenCase
from tests.evaluation.scorer import score

EVAL_DIR = Path(__file__).resolve().parent


def _load_golden(name: str) -> GoldenCase:
    p = EVAL_DIR / "goldens" / f"{name}.json"
    return GoldenCase.model_validate(json.loads(p.read_text(encoding="utf-8")))


def _load_fixture(name: str) -> ReviewSnapshot:
    p = EVAL_DIR / "fixtures" / f"{name}.snapshot.json"
    return ReviewSnapshot.model_validate(json.loads(p.read_text(encoding="utf-8")))


class TestScorer571(unittest.TestCase):
    def test_571_fixture_all_pass(self):
        g = _load_golden("qw-571")
        snap = _load_fixture("qw-571")
        card = score(g, snap)
        self.assertTrue(card.ok, [c.detail for c in card.failed])

    def test_571_request_changes_fails_final(self):
        g = _load_golden("qw-571")
        snap = _load_fixture("qw-571").model_copy(update={"final_decision": "REQUEST_CHANGES"})
        card = score(g, snap)
        self.assertFalse(card.ok)
        names = [c.name for c in card.failed]
        self.assertIn("final", names)

    def test_571_investigate_ran_fails(self):
        g = _load_golden("qw-571")
        snap = _load_fixture("qw-571").model_copy(
            update={"investigate_skipped": False, "skip_reason": None, "calls": 2}
        )
        card = score(g, snap)
        self.assertFalse(card.ok)
        names = [c.name for c in card.failed]
        self.assertIn("investigate", names)


class TestScorer538(unittest.TestCase):
    def test_538_fixture_all_pass(self):
        g = _load_golden("qw-538")
        snap = _load_fixture("qw-538")
        card = score(g, snap)
        self.assertTrue(card.ok, [c.detail for c in card.failed])

    def test_538_wordlist_hop_fails_jail(self):
        g = _load_golden("qw-538")
        snap = _load_fixture("qw-538").model_copy(
            update={"hyp_files": [".github/wordlist.txt", "api/core/pipeline.py"]}
        )
        card = score(g, snap)
        self.assertFalse(card.ok)
        names = [c.name for c in card.failed]
        self.assertIn("hops", names)

    def test_538_request_changes_without_supported_fails_clamp(self):
        g = _load_golden("qw-538")
        snap = _load_fixture("qw-538").model_copy(
            update={
                "final_decision": "REQUEST_CHANGES",
                "verify_supported": 0,
                "keep_verification_status": ["uncertain"],
                "keep_severity": ["concern"],
            }
        )
        card = score(g, snap)
        self.assertFalse(card.ok)
        names = [c.name for c in card.failed]
        self.assertIn("clamp", names)


class TestFromState(unittest.TestCase):
    def test_from_state_maps_keys(self):
        state = {
            "repo": "FalkorDB/QueryWeaver",
            "number": 571,
            "recommendation": "COMMENT",
            "files_changed": ["package-lock.json"],
            "pr_facts": {
                "classification": "lockfile-only",
                "files_changed": ["package-lock.json"],
                "lock_files": ["package-lock.json"],
                "source_files": [],
            },
            "investigation_report": {
                "skipped": True,
                "reason": "no_changed_path_hypotheses",
                "hops": 0,
                "calls": 0,
            },
            "validation_report": {"raw": 3, "kept": 1, "dropped": 0, "reasons": []},
            "validated_findings": [
                {
                    "file": "package-lock.json",
                    "verification_status": "supported",
                    "severity": "nit",
                }
            ],
            "verification_report": {
                "supported": 1,
                "uncertain": 0,
                "unsupported": 0,
                "tests_touched": 0,
                "suggested_recommendation": "COMMENT",
            },
            "execution_report": {"skipped": True, "skip_reason": "disabled"},
            "kb": None,
            "engine": None,
        }
        snap = from_state(state)
        self.assertEqual(snap.classification, "lockfile-only")
        self.assertTrue(snap.investigate_skipped)
        self.assertEqual(snap.keep_files, ["package-lock.json"])
        self.assertEqual(snap.final_decision, "COMMENT")
        self.assertFalse(snap.qdrant_used)


if __name__ == "__main__":
    unittest.main(verbosity=2)
