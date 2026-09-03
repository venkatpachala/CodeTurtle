"""Phase 6.1 — GitHub summary review posting. No live GitHub."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.github_review import (
    MARKER,
    already_posted,
    build_review_body,
    clamped_decision,
    github_event,
    keep_findings_for_body,
    post_pull_request_review,
    should_post,
)
from core.verification.policy import clamp_recommendation

LOCK = "package-lock.json"
PIPELINE = "api/core/pipeline.py"
WORDLIST = ".github/wordlist.txt"


class FakeReview:
    def __init__(self, url="https://github.com/o/r/pull/1#review"):
        self.html_url = url


class TestShouldPost(unittest.TestCase):
    def test_dry_run_default_no_post(self):
        self.assertFalse(should_post(dry_run=True, comment=False))

    def test_comment_flag_posts(self):
        self.assertTrue(should_post(dry_run=True, comment=True))

    def test_no_dry_run_posts(self):
        self.assertTrue(should_post(dry_run=False, comment=False))


class TestEventsAndClamp(unittest.TestCase):
    def test_571_event_is_comment(self):
        state = {
            "recommendation": "MERGE",
            "pr_facts": {"classification": "lockfile-only"},
            "validated_findings": [
                {
                    "file": LOCK,
                    "severity": "nit",
                    "verification_status": "supported",
                    "title": "lock bump",
                }
            ],
            "verification_report": {"ran": True, "suggested_recommendation": "COMMENT"},
        }
        rec = clamped_decision(state)
        self.assertEqual(rec, "COMMENT")
        self.assertEqual(github_event(rec, "lockfile-only"), "COMMENT")
        self.assertEqual(github_event("APPROVE", "lockfile-only"), "COMMENT")
        self.assertEqual(github_event("REQUEST_CHANGES", "lockfile-only"), "COMMENT")

    def test_538_request_changes_supported_zero_is_comment(self):
        state = {
            "recommendation": "REQUEST_CHANGES",
            "pr_facts": {"classification": "mixed"},
            "validated_findings": [
                {
                    "file": PIPELINE,
                    "severity": "concern",
                    "verification_status": "uncertain",
                    "title": "maybe",
                }
            ],
            "verification_report": {
                "ran": True,
                "supported": 0,
                "suggested_recommendation": "COMMENT",
            },
        }
        rec = clamped_decision(state)
        self.assertEqual(rec, "COMMENT")
        self.assertEqual(github_event(rec, "mixed"), "COMMENT")

    def test_source_supported_medium_request_changes(self):
        rec = clamp_recommendation("REQUEST_CHANGES", "REQUEST_CHANGES", "source")
        self.assertEqual(github_event(rec, "source"), "REQUEST_CHANGES")


class TestBody(unittest.TestCase):
    def test_keep_files_only_no_wordlist_no_empty(self):
        state = {
            "recommendation": "COMMENT",
            "pr_facts": {"classification": "mixed"},
            "pr_understanding": {"summary": "SQL Server loader"},
            "validated_findings": [
                {
                    "file": PIPELINE,
                    "severity": "concern",
                    "verification_status": "supported",
                    "claim": "error handling in pipeline",
                },
                {
                    "file": WORDLIST,
                    "severity": "nit",
                    "verification_status": "supported",
                    "claim": "wordlist",
                },
                {
                    "file": "",
                    "severity": "nit",
                    "verification_status": "uncertain",
                    "claim": "empty path",
                },
            ],
            "validation_report": {"kept": 1, "dropped": 12},
        }
        kept = keep_findings_for_body(state)
        self.assertEqual([k["file"] for k in kept], [PIPELINE])
        body = build_review_body(state, sha="abc123", decision="COMMENT")
        self.assertIn(MARKER, body)
        self.assertIn("codeturtle-sha:abc123", body)
        self.assertIn(PIPELINE, body)
        self.assertNotIn("wordlist", body)
        self.assertIn("dropped 12", body)
        self.assertIn("SQL Server loader", body)

    def test_lockfile_empty_keep_copy(self):
        state = {
            "recommendation": "COMMENT",
            "pr_facts": {"classification": "lockfile-only"},
            "validated_findings": [],
            "validation_report": {"kept": 0, "dropped": 0},
        }
        body = build_review_body(state, sha="s", decision="COMMENT")
        self.assertIn("No grounded issues; lockfile-only.", body)


class TestPost(unittest.TestCase):
    def test_dry_run_never_create_review(self):
        calls = []

        def create_review(**kwargs):
            calls.append(kwargs)
            return FakeReview()

        pr = MagicMock()
        pr.create_review = create_review
        pr.get_reviews.return_value = []
        self.assertFalse(should_post(dry_run=True, comment=False))
        self.assertEqual(calls, [])

    def test_post_sends_clamped_event(self):
        captured = {}

        def create_review(**kwargs):
            captured.update(kwargs)
            return FakeReview()

        pr = MagicMock()
        pr.html_url = "https://github.com/o/r/pull/571"
        pr.get_reviews.return_value = []
        state = {
            "recommendation": "MERGE",
            "pr_facts": {"classification": "lockfile-only"},
            "validated_findings": [
                {"file": LOCK, "severity": "nit", "verification_status": "supported", "title": "lock"}
            ],
            "pr_understanding": {"summary": "lockfile"},
            "validation_report": {"kept": 1, "dropped": 0},
        }
        out = post_pull_request_review(pr, state, sha="deadbeef", create_review=create_review)
        self.assertTrue(out.ok)
        self.assertEqual(out.event, "COMMENT")
        self.assertEqual(captured["event"], "COMMENT")
        self.assertIn(MARKER, captured["body"])
        self.assertIn(LOCK, captured["body"])

    def test_idempotent_skip_same_sha(self):
        calls = []

        def create_review(**kwargs):
            calls.append(kwargs)
            return FakeReview()

        prior = MagicMock()
        prior.body = f"{MARKER}\n{ '<!-- codeturtle-sha:abc -->' }\nhello"
        self.assertTrue(already_posted([prior], sha="abc"))
        pr = MagicMock()
        pr.get_reviews.return_value = [prior]
        state = {
            "recommendation": "COMMENT",
            "pr_facts": {"classification": "source"},
            "validated_findings": [
                {"file": PIPELINE, "severity": "nit", "verification_status": "uncertain", "title": "x"}
            ],
        }
        out = post_pull_request_review(pr, state, sha="abc", create_review=create_review)
        self.assertTrue(out.skipped)
        self.assertEqual(calls, [])

    def test_post_failure_not_ok(self):
        def create_review(**kwargs):
            raise RuntimeError("403 Resource not accessible")

        pr = MagicMock()
        pr.html_url = "https://github.com/o/r/pull/1"
        pr.get_reviews.return_value = []
        state = {
            "recommendation": "COMMENT",
            "pr_facts": {"classification": "source"},
            "validated_findings": [
                {"file": PIPELINE, "severity": "nit", "verification_status": "uncertain", "title": "x"}
            ],
        }
        out = post_pull_request_review(pr, state, sha="s", create_review=create_review)
        self.assertTrue(out.attempted)
        self.assertFalse(out.ok)
        self.assertIn("403", out.error)
        self.assertTrue(out.body)


if __name__ == "__main__":
    unittest.main(verbosity=2)
