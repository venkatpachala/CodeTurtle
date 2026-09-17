"""Tests for benchmark integration, structured JSON output, and adapter."""

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from benchmark.adapter import inject_review_into_benchmark_data, review_state_to_benchmark_review
from benchmark.models import BenchmarkFinding, BenchmarkReview
from cli.commands.review import ReviewPipeline


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

    def test_review_state_to_benchmark_review(self):
        state = {
            "repo": "keycloak/keycloak",
            "number": 37429,
            "recommendation": "MERGE",
            "policy_reason": "no_findings",
            "coverage_ratio": 0.35,
            "review_coverage": {"units_total": 55, "units_packed": 19},
            "validated_findings": [],
        }
        review = review_state_to_benchmark_review(state, elapsed=12.4, model="qwen2.5:7b")
        self.assertEqual(review.tool, "codeturtle")
        self.assertEqual(review.decision, "MERGE")
        self.assertEqual(review.coverage_total, 55)
        self.assertEqual(review.coverage_packed, 19)
        self.assertEqual(len(review.review_comments), 0)

    def test_pipeline_write_benchmark_json(self):
        pipe = ReviewPipeline()
        pipe.context.repo = "owner/repo"
        pipe.context.number = 99
        pipe.context.final_state = {
            "recommendation": "COMMENT",
            "policy_reason": "verified_nit",
            "coverage_ratio": 0.9,
            "review_coverage": {"units_total": 10, "units_packed": 9},
            "validated_findings": [
                {
                    "file": "server.py",
                    "start_line": 100,
                    "title": "Bug in handler",
                    "claim": "Missing check on status",
                    "verify_status": "verified",
                }
            ],
        }
        out_path = Path("benchmark/results/test_tmp_run.json")
        try:
            pipe._write_benchmark_json(str(out_path), elapsed=5.1)
            self.assertTrue(out_path.is_file())
            with open(out_path) as f:
                data = json.load(f)
            self.assertEqual(data["tool"], "codeturtle")
            self.assertEqual(data["decision"], "COMMENT")
            self.assertEqual(len(data["review_comments"]), 1)
            self.assertEqual(data["review_comments"][0]["path"], "server.py")
            self.assertEqual(data["review_comments"][0]["line"], 100)
            self.assertIn("Bug in handler", data["review_comments"][0]["body"])
        finally:
            if out_path.exists():
                out_path.unlink()


if __name__ == "__main__":
    unittest.main()
