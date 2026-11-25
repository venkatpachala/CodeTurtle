"""Classification and facts for lockfile pull requests."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.pr_facts import build_pr_facts, classify_change_set, format_pr_facts_for_prompt

LOCK = "package-lock.json"
LOADER = "api/loaders/sqlserver_loader.py"
WORDLIST = ".github/wordlist.txt"


class TestClassification(unittest.TestCase):
    def test_lockfile_only(self):
        kind = classify_change_set([LOCK])
        self.assertEqual(kind["classification"], "lockfile-only")
        self.assertEqual(kind["lock_files"], [LOCK])
        self.assertEqual(kind["source_files"], [])

    def test_source_and_mixed(self):
        src = classify_change_set([LOADER, WORDLIST])
        self.assertEqual(src["classification"], "source")
        mixed = classify_change_set([LOADER, LOCK])
        self.assertEqual(mixed["classification"], "mixed")

    def test_pr_facts_fields_and_prompt(self):
        facts = build_pr_facts(files_changed=[LOCK], title="chore: lockfile")
        self.assertEqual(facts["classification"], "lockfile-only")
        self.assertEqual(facts["lock_files"], [LOCK])
        block = format_pr_facts_for_prompt(facts)
        self.assertIn("classification: lockfile-only", block)
        self.assertIn("lock_files:", block)
        self.assertIn(LOCK, block)
