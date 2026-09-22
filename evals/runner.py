"""evals/runner.py — Main evaluation runner.

Usage:
    cd D:\CodeTurtle

    # Evaluate all available benchmark results
    uv run python -m evals.runner

    # Evaluate with a specific results dir
    uv run python -m evals.runner --results-dir benchmark/results --output eval_report.json

    # Evaluate only the reviewed PRs (no golden issues for un-reviewed PRs)
    uv run python -m evals.runner --only-reviewed

NO MOCKING. All metrics are computed against real benchmark data and real results.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import uuid
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional

# ── Dataset loader ─────────────────────────────────────────────────────────────

BENCHMARK_DATA_PATH = Path("D:/code-review-benchmark/code-review-benchmark/offline/results/benchmark_data.json")
DEFAULT_RESULTS_DIR = Path("benchmark/results")


def _load_benchmark_data() -> Dict[str, Any]:
    p = BENCHMARK_DATA_PATH
    if not p.is_file():
        print(f"[ERROR] benchmark_data.json not found at {p}", file=sys.stderr)
        sys.exit(1)
    with open(p, "r", encoding="utf-8") as f:
        return json.load(f)


def _load_results(results_dir: Path) -> List[Dict[str, Any]]:
    """Load all benchmark result JSON files from the results directory."""
    results = []
    for fp in sorted(results_dir.glob("*.json")):
        if fp.name in ("failures.json", "eval_report.json") or fp.name.startswith("eval_"):
            continue
        try:
            with open(fp, "r", encoding="utf-8") as f:
                r = json.load(f)
            # Ensure pr_url is present
            if "pr_url" not in r:
                print(f"  [WARN] Skipping {fp.name} — no pr_url", file=sys.stderr)
                continue
            r["_source_file"] = str(fp)
            results.append(r)
        except Exception as exc:
            print(f"  [WARN] Failed to load {fp.name}: {exc}", file=sys.stderr)
    # A benchmark PR must have exactly one prediction.  Keeping both an old
    # result and a re-run double-counts decisions and failure attribution.
    deduped: Dict[str, Dict[str, Any]] = {}
    for result in results:
        key = _normalise_url(str(result.get("pr_url") or ""))
        if not key:
            continue
        previous = deduped.get(key)
        if previous is None:
            deduped[key] = result
            continue
        current_mtime = Path(str(result["_source_file"])).stat().st_mtime
        previous_mtime = Path(str(previous["_source_file"])).stat().st_mtime
        chosen = result if current_mtime >= previous_mtime else previous
        discarded = previous if chosen is result else result
        deduped[key] = chosen
        print(
            f"  [WARN] Duplicate result for {result.get('pr_url')}; "
            f"using {Path(chosen['_source_file']).name}, ignoring {Path(discarded['_source_file']).name}",
            file=sys.stderr,
        )
    return list(deduped.values())


def _normalise_url(url: str) -> str:
    """Normalise a GitHub PR URL for matching."""
    return url.rstrip("/").lower().replace("https://github.com/", "")


def _map_results_to_golden(
    results: List[Dict[str, Any]],
    bm_data: Dict[str, Any],
) -> tuple:
    """
    Match result files to golden issues by PR URL.

    Returns:
        pr_results_map: {pr_url: [comment dicts]}
        golden_map: {pr_url: [GoldenIssue objects]}
        golden_count_map: {pr_url: int}
        decision_map: {pr_url: expected_decision}
    """
    from evals.review.findings import GoldenIssue, PredictedFinding

    # Build normalised golden lookup
    golden_norm: Dict[str, tuple] = {}
    for key, entry in bm_data.items():
        norm = _normalise_url(key)
        golden_norm[norm] = (key, entry)
        # Also try original_url
        orig = entry.get("original_url") or ""
        if orig:
            golden_norm[_normalise_url(orig)] = (key, entry)

    pr_results_map: Dict[str, List[Dict]] = {}
    golden_map: Dict[str, List[GoldenIssue]] = {}
    golden_count_map: Dict[str, int] = {}
    decision_map: Dict[str, str] = {}

    matched = 0
    for r in results:
        pr_url = r.get("pr_url", "")
        norm = _normalise_url(pr_url)

        # Find matching golden entry
        golden_entry = None
        for candidate_norm in [norm, norm + "/", norm.replace("/pull/", "#")]:
            if candidate_norm in golden_norm:
                golden_entry = golden_norm[candidate_norm]
                break

        if golden_entry is None:
            # Try fuzzy: match by repo + PR number from URL
            parts = norm.split("/")
            if len(parts) >= 4:
                repo_pr = f"{parts[-4]}/{parts[-3]}/pull/{parts[-1]}"
                for gnorm, ge in golden_norm.items():
                    if repo_pr in gnorm or gnorm.endswith(parts[-1]):
                        golden_entry = ge
                        break

        # Build PredictedFinding list from review_comments
        comments = r.get("review_comments") or []
        pr_results_map[pr_url] = comments

        if golden_entry:
            matched += 1
            _, entry = golden_entry
            golden_issues = []
            for i, gc in enumerate(entry.get("golden_comments") or []):
                golden_issues.append(GoldenIssue(
                    id=f"G-{i+1:03d}",
                    comment=str(gc.get("comment") or ""),
                    severity=str(gc.get("severity") or "Medium"),
                    category=str(gc.get("category") or ""),
                    pr_url=pr_url,
                ))
            golden_map[pr_url] = golden_issues
            golden_count_map[pr_url] = len(golden_issues)

            # Expected decision (infer from golden severity)
            sevs = [gc.get("severity", "Medium") for gc in (entry.get("golden_comments") or [])]
            if any(s in ("Critical", "High") for s in sevs):
                decision_map[pr_url] = "REQUEST_CHANGES"
            elif sevs:
                decision_map[pr_url] = "COMMENT"
            else:
                decision_map[pr_url] = "MERGE"
        else:
            print(f"  [WARN] No golden match for {pr_url}", file=sys.stderr)

    print(f"[Runner] Matched {matched}/{len(results)} result files to golden dataset")
    return pr_results_map, golden_map, golden_count_map, decision_map


def run_evaluation(
    results_dir: Path = DEFAULT_RESULTS_DIR,
    output_path: Optional[Path] = None,
    only_reviewed: bool = True,
    semantic_threshold: float = 0.12,
) -> Dict[str, Any]:
    """
    Run the full evaluation pipeline. Returns the JSON report dict.

    Steps:
      1. Load benchmark_data.json (golden)
      2. Load all result JSON files from results_dir
      3. Match results to golden issues
      4. Compute finding P/R/F1 (with bootstrap CI)
      5. Compute decision quality
      6. Compute pipeline survival funnel
      7. Attribute failures per missed golden issue
      8. Compute system latency statistics
      9. Print rich ASCII report
      10. Write JSON report to output_path
    """
    from evals.review.findings import (
        FindingMatcher,
        match_findings_to_golden,
        compute_finding_metrics,
        GoldenIssue,
    )
    from evals.review.decision import compute_decision_metrics
    from evals.review.survival import aggregate_survival_from_results
    from evals.review.failure import attribute_failures, FailureReport
    from evals.system.latency import compute_system_metrics
    from evals.reporting.console import print_report
    from evals.reporting.json_report import build_json_report

    run_id = str(uuid.uuid4())[:8]
    print(f"\n[Eval] run_id={run_id}")
    print(f"[Eval] Results dir: {results_dir}")
    print(f"[Eval] Benchmark data: {BENCHMARK_DATA_PATH}")

    # 1. Load data
    t0 = time.monotonic()
    bm_data = _load_benchmark_data()
    results = _load_results(results_dir)
    print(f"[Eval] Loaded {len(bm_data)} PRs from golden, {len(results)} result files")

    if not results:
        print("[Eval] No result files found. Run the benchmark runner first.", file=sys.stderr)
        sys.exit(1)

    # 2. Match results to golden
    pr_results_map, golden_map, golden_count_map, decision_map = _map_results_to_golden(results, bm_data)

    # 3. Finding matching
    matcher = FindingMatcher(semantic_threshold=semantic_threshold)
    pr_finding_results = match_findings_to_golden(pr_results_map, golden_map, matcher=matcher)

    # 4. Finding metrics
    finding_metrics = compute_finding_metrics(pr_finding_results)

    # 5. Decision metrics — compare predicted vs inferred expected decision
    pred_decisions = []
    gold_decisions = []
    for r in results:
        pr_url = r.get("pr_url", "")
        pred = r.get("decision") or "COMMENT"
        gold = decision_map.get(pr_url)
        if gold:
            pred_decisions.append(pred)
            gold_decisions.append(gold)
    decision_metrics = compute_decision_metrics(pred_decisions, gold_decisions)

    # 6. Pipeline survival funnel
    survival = aggregate_survival_from_results(results, golden_count_map)
    survival.total_golden = sum(golden_count_map.values())

    # 7. Failure attribution
    failure_report = FailureReport()
    failure_report.total_golden = finding_metrics.total_golden
    failure_report.total_tp = finding_metrics.total_tp
    failure_report.total_missed = finding_metrics.total_fn

    # Build golden_by_id lookup per PR
    for r in results:
        pr_url = r.get("pr_url", "")
        pr_result = next((x for x in pr_finding_results if x.pr_url == pr_url), None)
        if pr_result is None:
            continue
        golden_issues = golden_map.get(pr_url, [])
        golden_by_id = {g.id: g for g in golden_issues}

        failures = attribute_failures(
            pr_url,
            pr_result.unmatched_golden,
            golden_by_id,
            r,
        )
        for f in failures:
            failure_report.add_failure(f)

    failure_report.compute_percentages()

    # 8. System metrics
    system_metrics = compute_system_metrics(results)

    # 9. Print report
    model = (results[0].get("model") or "") if results else ""
    print_report(
        finding_metrics,
        decision_metrics,
        survival,
        failure_report,
        system_metrics,
        model=model,
        dataset_path=str(BENCHMARK_DATA_PATH),
        run_id=run_id,
    )

    elapsed = time.monotonic() - t0
    print(f"\n[Eval] Evaluation completed in {elapsed:.1f}s")

    # 10. JSON report
    report = build_json_report(
        finding_metrics,
        decision_metrics,
        survival,
        failure_report,
        system_metrics,
        model=model,
        dataset_path=str(BENCHMARK_DATA_PATH),
        run_id=run_id,
    )

    if output_path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2)
        print(f"[Eval] JSON report written to {output_path}")

    return report


def main():
    parser = argparse.ArgumentParser(
        description="CodeTurtle Evaluation Runner — computes real P/R/F1 and all pipeline metrics"
    )
    parser.add_argument(
        "--results-dir",
        default=str(DEFAULT_RESULTS_DIR),
        help="Directory containing benchmark result JSON files",
    )
    parser.add_argument(
        "--output",
        default="",
        help="Path for the JSON evaluation report (optional)",
    )
    parser.add_argument(
        "--semantic-threshold",
        type=float,
        default=0.12,
        help="Minimum Jaccard semantic similarity to count as a match (default: 0.12)",
    )
    args = parser.parse_args()

    results_dir = Path(args.results_dir)
    output_path = Path(args.output) if args.output else None

    run_evaluation(
        results_dir=results_dir,
        output_path=output_path,
        semantic_threshold=args.semantic_threshold,
    )


if __name__ == "__main__":
    main()
