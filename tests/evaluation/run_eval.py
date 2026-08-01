"""
Entry point for Repository Intelligence evaluation.

Usage:
    python -m tests.evaluation.run_eval
    python -m tests.evaluation.run_eval --repo isp1tze/MAProj --force
"""

import argparse
from tests.evaluation.test_repository_intelligence import RepositoryIntelligenceEvaluator


def main():
    parser = argparse.ArgumentParser(description="Evaluate Repository Intelligence")
    parser.add_argument(
        "--repo",
        default="isp1tze/MAProj",
        help="Repository in owner/repo format"
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Force re-indexing before evaluation"
    )
    args = parser.parse_args()

    evaluator = RepositoryIntelligenceEvaluator(
        repo_name=args.repo,
        force_reindex=args.force
    )
    report = evaluator.run()

    # Exit code for CI
    exit(0 if report.passed else 1)


if __name__ == "__main__":
    main()