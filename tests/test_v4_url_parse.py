"""V4.0 — parse_review_target. Synthetic slugs only."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.cli_parse import parse_review_target


class TestParseReviewTarget(unittest.TestCase):
    def test_owner_repo_space_number(self):
        self.assertEqual(parse_review_target("acme/widgets 42"), ("acme/widgets", 42))

    def test_owner_repo_hash_number(self):
        self.assertEqual(parse_review_target("acme/widgets#7"), ("acme/widgets", 7))

    def test_https_pull_url(self):
        self.assertEqual(
            parse_review_target("https://github.com/acme/widgets/pull/99"),
            ("acme/widgets", 99),
        )

    def test_https_pull_url_trailing_slash(self):
        self.assertEqual(
            parse_review_target("https://github.com/acme/widgets/pull/99/"),
            ("acme/widgets", 99),
        )

    def test_http_and_files_suffix(self):
        self.assertEqual(
            parse_review_target("http://github.com/acme/widgets/pull/3/files"),
            ("acme/widgets", 3),
        )

    def test_extra_whitespace(self):
        self.assertEqual(
            parse_review_target("  acme/widgets    12  "),
            ("acme/widgets", 12),
        )

    def test_empty_raises(self):
        with self.assertRaises(ValueError):
            parse_review_target("")

    def test_missing_number_raises(self):
        with self.assertRaises(ValueError):
            parse_review_target("acme/widgets")

    def test_zero_number_raises(self):
        with self.assertRaises(ValueError):
            parse_review_target("acme/widgets#0")


if __name__ == "__main__":
    unittest.main(verbosity=2)
