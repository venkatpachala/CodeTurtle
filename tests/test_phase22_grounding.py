"""PR facts and diff statistics used by review intake."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.pr_facts import (
    build_pr_facts,
    extract_diff_symbols,
)


LOADER = "api/loaders/sqlserver_loader.py"
WORDLIST = ".github/wordlist.txt"
GITIGNORE = ".gitignore"

DIFF = f"""diff --git a/{LOADER} b/{LOADER}
--- a/{LOADER}
+++ b/{LOADER}
@@ -40,6 +40,10 @@ class SQLServerLoader:
     def load_schema(self):
         cursor = self.connection.cursor()
+        if not cursor:
+            raise RuntimeError("no cursor")
         return cursor.fetchall()

diff --git a/{WORDLIST} b/{WORDLIST}
--- a/{WORDLIST}
+++ b/{WORDLIST}
@@ -1,0 +1,1 @@
+sqlserver
"""

FILES = [LOADER, WORDLIST, GITIGNORE]


def _facts():
    return build_pr_facts(
        title="Fix SQL Server loader",
        files_changed=FILES,
        full_diff=DIFF,
        pr_number=538,
        repo="owner/queryweaver",
    )


class TestDiffstat(unittest.TestCase):
    def test_git_headers_count_files(self):
        facts = _facts()
        self.assertGreaterEqual(facts["diff_stat"]["files_in_diff"], 2)
        self.assertIn(LOADER, facts["files_changed"])
        self.assertIn(LOADER, facts["paths_in_diff"])
        self.assertGreater(facts["diff_bytes"], 100)

    def test_github_style_headers_without_diff_git(self):
        # Old construction: `--- filename` / `+++ filename` + hunk only
        githubish = (
            f"--- {LOADER}\n+++ {LOADER}\n"
            "@@ -1,1 +1,2 @@\n"
            " def load_schema():\n"
            "+    pass\n"
        )
        facts = build_pr_facts(files_changed=[LOADER], full_diff=githubish)
        self.assertGreaterEqual(facts["diff_stat"]["files_in_diff"], 1)
        self.assertIn(LOADER, facts["paths_in_diff"])

    def test_empty_diff_with_files_still_lists_github_paths(self):
        facts = build_pr_facts(files_changed=[LOADER], full_diff="")
        self.assertEqual(facts["file_count"], 1)
        self.assertEqual(facts["diff_stat"]["files_in_diff"], 0)

    def test_extract_def_class_from_diff(self):
        syms = extract_diff_symbols(DIFF)
        self.assertIn("SQLServerLoader", syms)
        self.assertIn("load_schema", syms)
