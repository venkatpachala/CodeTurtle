"""benchmark/integrate.py - Integrate CodeTurtle reviews into benchmark_data.json."""

from __future__ import annotations

import argparse
import glob
import json
import sys
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parents[1]
_nested = (
    ROOT.parent
    / "code-review-benchmark"
    / "code-review-benchmark"
    / "offline"
    / "results"
    / "benchmark_data.json"
)
_flat = (
    ROOT.parent
    / "code-review-benchmark"
    / "offline"
    / "results"
    / "benchmark_data.json"
)
DEFAULT_DATASET = _nested if _nested.is_file() else _flat
DEFAULT_RESULTS = ROOT / "benchmark" / "results"


def integrate_results(
    dataset_path: Path,
    results_dir: Path,
    tool_name: str = "codeturtle",
) -> tuple[int, int]:
    if not dataset_path.is_file():
        raise FileNotFoundError(f"Dataset not found: {dataset_path}")

    with dataset_path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    json_files = [
        Path(p)
        for p in glob.glob(str(results_dir / "*.json"))
        if not p.endswith("failures.json") and not p.endswith("codeturtle_reviews.json")
    ]

    print(f"Dataset: {dataset_path}")
    print(f"Found {len(json_files)} result JSON files in {results_dir}")

    updated_count = 0
    total_comments = 0

    for jf in json_files:
        try:
            with jf.open("r", encoding="utf-8") as f:
                review_data = json.load(f)
        except Exception as exc:
            print(f"Warning: Could not read {jf}: {exc}")
            continue

        pr_url = review_data.get("pr_url") or ""
        if not pr_url:
            continue

        clean_url = pr_url.rstrip("/").lower()

        # Find matching entry in benchmark_data.json
        matched_key = None
        for key, entry in data.items():
            if key.rstrip("/").lower() == clean_url:
                matched_key = key
                break
            if str(entry.get("original_url") or "").rstrip("/").lower() == clean_url:
                matched_key = key
                break

        if not matched_key:
            print(f"Warning: No match in dataset for {pr_url}")
            continue

        entry = data[matched_key]
        reviews: List[Dict[str, Any]] = entry.setdefault("reviews", [])

        # Build clean benchmark review comment objects
        clean_comments = []
        for c in review_data.get("review_comments") or []:
            if isinstance(c, dict) and "path" in c and "body" in c:
                clean_comments.append(
                    {
                        "path": c["path"],
                        "line": c.get("line"),
                        "body": c["body"],
                    }
                )

        target_review = {
            "tool": tool_name,
            "pr_url": pr_url,
            "review_comments": clean_comments,
        }

        # Update or append
        existing_idx = None
        for idx, r in enumerate(reviews):
            if str(r.get("tool") or "").lower() == tool_name.lower():
                existing_idx = idx
                break

        if existing_idx is not None:
            reviews[existing_idx] = target_review
        else:
            reviews.append(target_review)

        updated_count += 1
        total_comments += len(clean_comments)

    with dataset_path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

    print(f"\nSuccessfully integrated {updated_count} PR reviews ({total_comments} total comments) into {dataset_path}")
    return updated_count, total_comments


def main() -> int:
    parser = argparse.ArgumentParser(description="Integrate CodeTurtle results into benchmark_data.json")
    parser.add_argument(
        "--dataset",
        type=Path,
        default=DEFAULT_DATASET,
        help="Path to benchmark_data.json",
    )
    parser.add_argument(
        "--results",
        type=Path,
        default=DEFAULT_RESULTS,
        help="Directory with CodeTurtle JSON results",
    )
    parser.add_argument(
        "--tool",
        type=str,
        default="codeturtle",
        help="Tool identifier (default: codeturtle)",
    )
    args = parser.parse_args()

    integrate_results(args.dataset, args.results, tool_name=args.tool)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
