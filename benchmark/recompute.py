"""Re-evaluate saved predictions without rerunning the review model."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from benchmark.dataset import load_dataset
from benchmark.evaluator import evaluate_pr
from benchmark.gates import evaluate_release_gate
from benchmark.metrics import aggregate_metrics
from benchmark.reports import render_ascii, render_gate, write_aggregate


def recompute(run_dir: Path) -> dict:
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    dataset = load_dataset(str(manifest["dataset_path"]))
    golden_by_url = {
        pr.pr_url: [vars(item) for item in pr.golden_comments] for pr in dataset
    }
    predictions = []
    evaluations = []
    eval_dir = run_dir / "evaluations"
    eval_dir.mkdir(exist_ok=True)
    for prediction_path in sorted((run_dir / "predictions").glob("*.json")):
        prediction = json.loads(prediction_path.read_text(encoding="utf-8"))
        pr_url = str(prediction.get("pr_url") or "")
        evaluation = evaluate_pr(prediction, golden_by_url.get(pr_url, []))
        evaluation["pr_url"] = pr_url
        (eval_dir / prediction_path.name).write_text(
            json.dumps(evaluation, indent=2), encoding="utf-8"
        )
        predictions.append(prediction)
        evaluations.append(evaluation)
    metrics = aggregate_metrics(evaluations, predictions)
    thresholds = (manifest.get("config") or {}).get("release_gate") or {}
    aggregate = {
        "run_id": manifest.get("run_id") or run_dir.name,
        "metrics": metrics,
        "release_gate": evaluate_release_gate(metrics, thresholds),
        "failures": manifest.get("failures") or [],
    }
    write_aggregate(run_dir / "aggregate.json", aggregate)
    return aggregate


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("run_dir", type=Path)
    args = parser.parse_args()
    aggregate = recompute(args.run_dir.resolve())
    print(render_ascii(aggregate["metrics"]))
    print(render_gate(aggregate["release_gate"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
