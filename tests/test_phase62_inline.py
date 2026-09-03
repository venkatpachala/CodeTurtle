"""Phase 6.2 — inline GitHub review comments. No live GitHub."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.github_review import (
    already_posted,
    build_inline_comments,
    github_event,
    post_pull_request_review,
    should_post,
)
from core.verification.diff_index import build_diff_index
from core.verification.policy import clamp_recommendation

SANITIZER = "api/sql_utils/sql_sanitizer.py"
PIPELINE = "api/core/pipeline.py"
LOCK = "package-lock.json"
WORDLIST = ".github/wordlist.txt"

DIFF_A = f"""diff --git a/{SANITIZER} b/{SANITIZER}
--- a/{SANITIZER}
+++ b/{SANITIZER}
@@ -1,3 +1,8 @@
+class SQLIdentifierQuoter:
+    def quote(self, name):
+        return name
 context
"""

DIFF_C = f"""diff --git a/{SANITIZER} b/{SANITIZER}
--- a/{SANITIZER}
+++ b/{SANITIZER}
@@ -40,2 +40,10 @@ class SQLIdentifierQuoter:
     def quote(self, name):
+        if not name:
+            return ""
         return name
"""


class FakeReview:
    def __init__(self, url="https://github.com/o/r/pull/1#review"):
        self.html_url = url


def _state_supported(diff=DIFF_A, start_line=2, extra=None):
    st = {
        "recommendation": "COMMENT",
        "full_diff": diff,
        "files_changed": [SANITIZER],
        "pr_facts": {
            "classification": "source",
            "files_changed": [SANITIZER],
            "source_files": [SANITIZER],
        },
        "validated_findings": [
            {
                "title": "quoter",
                "file": SANITIZER,
                "severity": "concern",
                "verification_status": "supported",
                "claim": "SQLIdentifierQuoter quoting",
                "start_line": start_line,
                "hunk_header": "@@ -1,3 +1,8 @@",
                "matched_tokens": ["SQLIdentifierQuoter"],
            }
        ],
        "validation_report": {"kept": 1, "dropped": 0},
        "pr_understanding": {"summary": "sanitizer"},
    }
    if extra:
        st.update(extra)
    return st


class TestLineResolution(unittest.TestCase):
    def test_start_line_in_hunk(self):
        idx = build_diff_index(DIFF_A)
        self.assertEqual(idx.line_for_finding(SANITIZER, start_line=2), 2)

    def test_token_hunk_new_start(self):
        idx = build_diff_index(DIFF_A)
        line = idx.line_for_finding(
            SANITIZER,
            start_line=900,
            hunk_header="@@ -1,3 +1,8 @@",
            tokens=["SQLIdentifierQuoter"],
        )
        self.assertEqual(line, 1)

    def test_first_plus_when_no_header(self):
        idx = build_diff_index(DIFF_C)
        line = idx.line_for_finding(SANITIZER, start_line=None)
        self.assertEqual(line, 41)

    def test_no_hunk_returns_none(self):
        idx = build_diff_index(DIFF_A)
        self.assertIsNone(idx.line_for_finding(PIPELINE, start_line=1))


class TestInlineSelection(unittest.TestCase):
    def test_supported_emits_right_side_comment(self):
        comments, skipped = build_inline_comments(_state_supported())
        self.assertEqual(len(comments), 1)
        self.assertEqual(skipped, 0)
        c = comments[0]
        self.assertEqual(c["path"], SANITIZER)
        self.assertEqual(c["side"], "RIGHT")
        self.assertEqual(c["line"], 2)
        self.assertIn("quoter", c["body"])

    def test_uncertain_zero_inlines(self):
        st = _state_supported()
        st["validated_findings"][0]["verification_status"] = "uncertain"
        comments, _ = build_inline_comments(st)
        self.assertEqual(comments, [])

    def test_supported_no_line_skip(self):
        st = _state_supported(diff=DIFF_A, start_line=None)
        st["validated_findings"][0]["hunk_header"] = ""
        st["validated_findings"][0]["matched_tokens"] = []
        st["validated_findings"][0]["file"] = PIPELINE
        st["pr_facts"]["files_changed"] = [PIPELINE]
        st["files_changed"] = [PIPELINE]
        st["full_diff"] = f"diff --git a/{PIPELINE} b/{PIPELINE}\n"
        comments, skipped = build_inline_comments(st)
        self.assertEqual(comments, [])
        self.assertGreaterEqual(skipped, 1)

    def test_lockfile_only_zero_inlines(self):
        st = {
            "recommendation": "COMMENT",
            "full_diff": f"diff --git a/{LOCK} b/{LOCK}\n--- a/{LOCK}\n+++ b/{LOCK}\n@@ -1,1 +1,2 @@\n+x\n",
            "pr_facts": {
                "classification": "lockfile-only",
                "files_changed": [LOCK],
            },
            "validated_findings": [
                {
                    "title": "lock",
                    "file": LOCK,
                    "severity": "concern",
                    "verification_status": "supported",
                    "start_line": 1,
                    "hunk_header": "@@ -1,1 +1,2 @@",
                }
            ],
        }
        comments, _ = build_inline_comments(st)
        self.assertEqual(comments, [])
        self.assertEqual(github_event("MERGE", "lockfile-only"), "COMMENT")
        self.assertEqual(clamp_recommendation("MERGE", "COMMENT", "lockfile-only"), "COMMENT")

    def test_trivia_no_inline(self):
        st = _state_supported()
        st["validated_findings"][0]["file"] = WORDLIST
        st["files_changed"] = [WORDLIST]
        st["pr_facts"]["files_changed"] = [WORDLIST]
        comments, _ = build_inline_comments(st)
        self.assertEqual(comments, [])

    def test_cap_eight(self):
        st = _state_supported()
        findings = []
        for i in range(12):
            findings.append(
                {
                    "title": f"f{i}",
                    "file": SANITIZER,
                    "severity": "nit" if i < 10 else "high",
                    "verification_status": "supported",
                    "start_line": 2,
                    "claim": f"claim {i}",
                }
            )
        st["validated_findings"] = findings
        comments, skipped = build_inline_comments(st, inline_max=8)
        self.assertEqual(len(comments), 8)
        self.assertGreaterEqual(skipped, 4)
        # higher severity first
        self.assertIn("high", comments[0]["body"])


class TestPostInlines(unittest.TestCase):
    def test_dry_run_no_create_review(self):
        self.assertFalse(should_post(dry_run=True, comment=False))

    def test_post_includes_comments(self):
        captured = {}

        def create_review(**kwargs):
            captured.update(kwargs)
            return FakeReview()

        pr = MagicMock()
        pr.html_url = "https://github.com/o/r/pull/1"
        pr.get_reviews.return_value = []
        out = post_pull_request_review(
            pr, _state_supported(), sha="abc", create_review=create_review
        )
        self.assertTrue(out.ok)
        self.assertEqual(out.inlines, 1)
        self.assertEqual(len(captured.get("comments") or []), 1)
        self.assertEqual(captured["comments"][0]["side"], "RIGHT")
        self.assertEqual(captured["event"], "COMMENT")

    def test_api_line_error_retries_summary(self):
        calls = []

        def create_review(**kwargs):
            calls.append(dict(kwargs))
            if kwargs.get("comments"):
                raise RuntimeError("422 Validation Failed: line is not part of the diff")
            return FakeReview()

        pr = MagicMock()
        pr.get_reviews.return_value = []
        out = post_pull_request_review(
            pr, _state_supported(), sha="abc", create_review=create_review
        )
        self.assertTrue(out.ok)
        self.assertGreaterEqual(len(calls), 2)
        self.assertFalse(calls[-1].get("comments"))
        self.assertEqual(out.inlines, 0)

    def test_same_sha_skips_inlines_too(self):
        calls = []

        def create_review(**kwargs):
            calls.append(kwargs)
            return FakeReview()

        prior = MagicMock()
        prior.body = "<!-- codeturtle-review -->\n<!-- codeturtle-sha:abc -->\n"
        self.assertTrue(already_posted([prior], sha="abc"))
        pr = MagicMock()
        pr.get_reviews.return_value = [prior]
        out = post_pull_request_review(
            pr, _state_supported(), sha="abc", create_review=create_review
        )
        self.assertTrue(out.skipped)
        self.assertEqual(calls, [])
        self.assertEqual(out.inlines, 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
