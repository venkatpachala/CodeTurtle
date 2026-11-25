"""Tests for benchmark integration, structured JSON output, and adapter."""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from benchmark.models import BenchmarkFinding, BenchmarkReview


class TestBenchmarkIntegration(unittest.TestCase):
    def test_benchmark_models_serialization(self):
        f = BenchmarkFinding(path="pkg/loader.py", line=15, body="Potential race condition")
        r = BenchmarkReview(
            tool="codeturtle",
            pr_url="https://github.com/org/repo/pull/1",
            repo_name="org/repo",
            decision="REQUEST_CHANGES",
            review_comments=[f],
        )
        d = r.to_dict()
        self.assertEqual(d["tool"], "codeturtle")
        self.assertEqual(len(d["review_comments"]), 1)
        self.assertEqual(d["review_comments"][0]["path"], "pkg/loader.py")
        self.assertEqual(d["review_comments"][0]["line"], 15)

        bm_d = r.to_benchmark_data_review()
        self.assertEqual(bm_d["tool"], "codeturtle")
        self.assertIn("created_at", bm_d["review_comments"][0])

if __name__ == "__main__":
    unittest.main()
