"""benchmark/runner.py - Automated runner for Code Review Benchmark PRs."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

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


def parse_pr_url(pr_url: str) -> tuple[str, int]:
    parsed = urlparse(pr_url)
    parts = [p for p in parsed.path.split("/") if p]

    if len(parts) < 4 or parts[2] != "pull":
        raise ValueError(f"Invalid PR URL: {pr_url}")

    repo = f"{parts[0]}/{parts[1]}"
    number = int(parts[3])
    return repo, number


def load_dataset(path: Path) -> list[dict]:
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    if isinstance(data, dict):
        if "reviews" in data and isinstance(data["reviews"], list):
            return data["reviews"]
        # benchmark_data.json is a dict mapping PR URL -> entry
        items = []
        for url, entry in data.items():
            pr_url = entry.get("original_url") or url
            items.append({"pr_url": pr_url, **entry})
        return items
    elif isinstance(data, list):
        return data
    else:
        raise ValueError("Unsupported benchmark_data.json format")


def run_pr(
    repo: str,
    number: int,
    output_path: Path,
    model: str,
) -> tuple[int, float]:
    output_path.parent.mkdir(parents=True, exist_ok=True)

    env = os.environ.copy()
    env["OLLAMA_MODEL"] = model

    command = [
        "uv",
        "run",
        "python",
        "-m",
        "cli.main",
        "review",
        repo,
        str(number),
        "--dry-run",
        "--json-output",
        str(output_path),
    ]

    start = time.perf_counter()

    completed = subprocess.run(
        command,
        cwd=ROOT,
        text=True,
        capture_output=True,
        env=env,
    )

    elapsed = time.perf_counter() - start

    log_path = output_path.with_suffix(".log")
    log_path.write_text(
        completed.stdout + "\n" + completed.stderr,
        encoding="utf-8",
    )

    return completed.returncode, elapsed


def main() -> int:
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--dataset",
        type=Path,
        default=DEFAULT_DATASET,
    )
    parser.add_argument(
        "--results",
        type=Path,
        default=DEFAULT_RESULTS,
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
    )
    parser.add_argument(
        "--model",
        default="qwen2.5:7b",
    )
    parser.add_argument(
        "--start",
        type=int,
        default=0,
    )

    args = parser.parse_args()

    reviews = load_dataset(args.dataset)

    selected = reviews[
        args.start : (
            args.start + args.limit if args.limit is not None else None
        )
    ]

    args.results.mkdir(parents=True, exist_ok=True)

    failures = []

    print(f"Dataset: {args.dataset}")
    print(f"PRs selected: {len(selected)}")
    print(f"Model: {args.model}")

    for index, item in enumerate(selected, start=args.start):
        pr_url = item["pr_url"]

        try:
            repo, number = parse_pr_url(pr_url)

            safe_repo = repo.replace("/", "_")
            output_path = args.results / f"{safe_repo}_{number}.json"

            # Skip PRs that already completed successfully.
            if output_path.exists():
                try:
                    existing = json.loads(
                        output_path.read_text(encoding="utf-8")
                    )

                    existing_url = str(existing.get("pr_url") or "").rstrip("/").lower()
                    if existing_url == pr_url.rstrip("/").lower():
                        print(
                            f"[{index + 1}/{len(reviews)}] "
                            f"{repo}#{number} SKIP already completed",
                            flush=True,
                        )
                        continue

                except Exception:
                    # Corrupt/incomplete JSON -> rerun it.
                    pass

            print(
                f"\n[{index + 1}/{len(reviews)}] "
                f"{repo}#{number}",
                flush=True,
            )

            return_code, elapsed = run_pr(
                repo=repo,
                number=number,
                output_path=output_path,
                model=args.model,
            )

            if return_code != 0:
                failures.append(
                    {
                        "pr_url": pr_url,
                        "repo": repo,
                        "number": number,
                        "return_code": return_code,
                        "elapsed_seconds": elapsed,
                    }
                )
                print(f"FAILED return_code={return_code}")
            else:
                print(f"OK elapsed={elapsed:.2f}s output={output_path}")

        except Exception as exc:
            failures.append(
                {
                    "pr_url": pr_url,
                    "error": repr(exc),
                }
            )
            print(f"ERROR: {exc}")

    failure_path = args.results / "failures.json"
    failure_path.write_text(
        json.dumps(failures, indent=2),
        encoding="utf-8",
    )

    print("\nFinished.")
    print(f"Results: {args.results}")
    print(f"Failures: {len(failures)}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
