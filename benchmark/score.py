"""Score sealed predictions after gold-label adjudication, without rerunning reviews."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

from benchmark.dataset import load_dataset
from benchmark.evaluator import evaluate_pr
from benchmark.gates import evaluate_release_gate
from benchmark.gold import load_adjudications, statuses_for_pr
from benchmark.failure_adjudication import load_failure_adjudications
from benchmark.issue_trace import trace_gold_issues
from benchmark.metrics import aggregate_metrics
from benchmark.reports import render_ascii, render_gate, write_aggregate
from benchmark.splits import load_registered_splits, load_split


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def score_run(
    run_dir: Path, adjudications_path: Path, supplement_runs: list[Path] | None = None,
    failure_adjudications_path: Path | None = None,
) -> dict[str, Any]:
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    metadata = manifest.get("metadata") or {}
    if not manifest.get("completed_at") or not metadata.get("split_name"):
        raise ValueError("Run is not a sealed split prediction run")
    if metadata.get("split_manifest"):
        split = load_split(metadata["split_manifest"])
    else:
        registered = load_registered_splits(Path(__file__).resolve().parent / "datasets")
        matching = [item for item in registered if item.name == metadata["split_name"]]
        if len(matching) != 1:
            raise ValueError("Frozen split name does not resolve uniquely")
        split = matching[0]
    if _sha256(split.path) != metadata.get("split_manifest_sha256"):
        raise ValueError("Split manifest changed after prediction; refusing to score")
    source = Path(manifest["dataset_path"])
    if _sha256(source) != metadata.get("dataset_sha256"):
        raise ValueError("Gold dataset changed after prediction; refusing to score")
    data = {pr.pr_url: pr for pr in load_dataset(str(source))}
    adjudications = load_adjudications(adjudications_path)
    failure_adjudications = (
        load_failure_adjudications(failure_adjudications_path)
        if failure_adjudications_path is not None else {}
    )
    used_failure_adjudications: set[tuple[str, str]] = set()
    predictions = [json.loads(path.read_text(encoding="utf-8")) for path in sorted((run_dir / "predictions").glob("pr_*.json"))]
    original_count = len(predictions)
    if original_count != int(manifest.get("prs_completed") or 0):
        raise ValueError("Prediction count differs from sealed manifest")
    run_sources = [manifest["run_id"]]
    retry_failures: list[dict[str, Any]] = []
    for supplement in supplement_runs or []:
        extra_manifest = json.loads((supplement / "manifest.json").read_text(encoding="utf-8"))
        extra_meta = extra_manifest.get("metadata") or {}
        extra_config = extra_manifest.get("config") or {}
        base_config = manifest.get("config") or {}
        comparable = ("model", "provider", "runtime", "bundle_max", "agent_max_steps", "verification_enabled", "execution_enabled")
        if not extra_manifest.get("completed_at") or any(extra_config.get(key) != base_config.get(key) for key in comparable):
            raise ValueError(f"Supplement run config differs or is not sealed: {supplement}")
        for key in ("commit", "dataset_sha256", "split_name", "split_manifest_sha256"):
            if extra_meta.get(key) != metadata.get(key):
                raise ValueError(f"Supplement run has different frozen provenance ({key}): {supplement}")
        extra_predictions = [json.loads(path.read_text(encoding="utf-8")) for path in sorted((supplement / "predictions").glob("pr_*.json"))]
        if len(extra_predictions) != int(extra_manifest.get("prs_completed") or 0):
            raise ValueError(f"Supplement prediction count mismatch: {supplement}")
        predictions.extend(extra_predictions)
        retry_failures.extend(extra_manifest.get("failures") or [])
        run_sources.append(extra_manifest["run_id"])
    urls = [str(pred.get("pr_url") or "") for pred in predictions]
    if len(urls) != len(set(urls)):
        raise ValueError("A supplement attempted to replace an existing prediction; only missing PRs may be retried")
    selected = set(split.prs)
    if any(pred.get("pr_url") not in selected for pred in predictions):
        raise ValueError("Prediction URL is outside the frozen split")

    provisional_evaluations: list[dict[str, Any]] = []
    confirmed_evaluations: list[dict[str, Any]] = []
    confirmed_predictions: list[dict[str, Any]] = []
    traces: list[dict[str, Any]] = []
    unscored_prs: list[dict[str, Any]] = []
    provisional_false_positives: list[dict[str, Any]] = []
    label_counts: Counter[str] = Counter()
    for prediction in predictions:
        url = str(prediction["pr_url"])
        pr = data.get(url)
        if pr is None:
            raise ValueError(f"No source gold entry for prediction: {url}")
        goldens = [vars(g) for g in pr.golden_comments]
        statuses = statuses_for_pr(url, goldens, adjudications)
        label_counts.update(item.status for item in statuses)
        provisional = evaluate_pr(prediction, goldens)
        provisional["pr_url"] = url
        provisional_evaluations.append(provisional)
        provisional_false_positives.extend({
            "pr_url": url,
            "finding": item.get("finding"),
            "attribution": "requires_manual_adjudication",
        } for item in provisional.get("false_positives") or [])
        # Provisional traces help adjudication but cannot be headline evidence.
        for trace, status in zip(trace_gold_issues(prediction, provisional, goldens), statuses):
            record = trace.to_dict()
            record["gold_status"] = status.status
            key = (url, record["gold_id"])
            if key in failure_adjudications:
                if status.status != "confirmed" or record["final_match"]:
                    raise ValueError(f"Manual failure attribution is not a confirmed FN: {key}")
                audited = failure_adjudications[key]
                record["automatic_failure_stage"] = record["failure_stage"]
                record["failure_stage"] = audited["failure_stage"]
                record["manual_evidence"] = audited["evidence"]
                record["notes"].append(audited["rationale"])
                record["link_basis"] = "manual_issue_audit"
                used_failure_adjudications.add(key)
            traces.append(record)
        unresolved = [item.gold_id for item in statuses if item.status in {"ambiguous", "adjudication_required"}]
        if unresolved:
            unscored_prs.append({"pr_url": url, "unresolved_gold_ids": unresolved})
            continue
        confirmed = [gold for gold, status in zip(goldens, statuses) if status.status == "confirmed"]
        evaluation = evaluate_pr(prediction, confirmed)
        evaluation["pr_url"] = url
        confirmed_evaluations.append(evaluation)
        confirmed_predictions.append(prediction)
    if set(failure_adjudications) != used_failure_adjudications:
        raise ValueError(f"Unused manual failure adjudications: {sorted(set(failure_adjudications) - used_failure_adjudications)}")

    provisional_metrics = aggregate_metrics(provisional_evaluations, predictions)
    metrics = aggregate_metrics(confirmed_evaluations, confirmed_predictions) if confirmed_evaluations else None
    thresholds = dict((manifest.get("config") or {}).get("release_gate") or {})
    gate_metrics = dict(metrics) if metrics is not None else None
    if gate_metrics is not None:
        # System metrics concern every completed review, including a PR whose
        # labels remain unresolved; quality metrics concern adjudicated PRs.
        gate_metrics["latency_seconds"] = provisional_metrics["latency_seconds"]
        gate_metrics["agent_run_success_rate"] = provisional_metrics["agent_run_success_rate"]
    gate = evaluate_release_gate(gate_metrics, thresholds) if gate_metrics is not None else {
        "passed": False, "checks": {"confirmed_sample": False}, "observed": {}, "thresholds": thresholds,
    }
    if unscored_prs or manifest.get("failures") or len(predictions) != len(split.prs):
        gate["passed"] = False
        gate["checks"]["run_and_labels_complete"] = False
    incidents = [
        {**failure, "recovered_by_supplement": failure.get("pr_url") in set(urls)}
        for failure in [*(manifest.get("failures") or []), *retry_failures]
    ]
    distribution = Counter(trace["failure_stage"] for trace in traces if not trace["final_match"])
    confirmed_distribution = Counter(
        trace["failure_stage"] for trace in traces
        if trace["gold_status"] == "confirmed" and not trace["final_match"]
    )
    confirmed_gold_count = sum(trace["gold_status"] == "confirmed" for trace in traces)
    confirmed_detected = sum(
        trace["gold_status"] == "confirmed" and trace["final_match"] for trace in traces
    )
    aggregate = {
        "run_id": manifest["run_id"],
        "split": split.split,
        "split_name": split.name,
        "eligible_for_headline_metrics": split.eligible_for_headline_metrics,
        "reviewer_commit": metadata.get("commit"),
        "reviewer_dirty": metadata.get("reviewer_dirty"),
        "dataset_sha256": metadata.get("dataset_sha256"),
        "adjudications_sha256": _sha256(adjudications_path),
        "failure_adjudications_sha256": _sha256(failure_adjudications_path) if failure_adjudications_path else None,
        "prs_selected": len(split.prs),
        "prs_predicted": len(predictions),
        "prediction_run_sources": run_sources,
        "label_counts": dict(label_counts),
        "confirmed_known_issue_detection": {
            "gold_count": confirmed_gold_count,
            "detected": confirmed_detected,
            "recall": round(confirmed_detected / confirmed_gold_count, 4) if confirmed_gold_count else None,
            "note": "Issue-level recall only; unresolved PRs prevent valid precision/FP scoring",
        },
        "unscored_prs": unscored_prs,
        "metrics": metrics,
        "provisional_metrics": provisional_metrics,
        "failure_attribution": dict(confirmed_distribution),
        "provisional_failure_attribution": dict(distribution),
        "provisional_false_positives": provisional_false_positives,
        "infrastructure_incidents": incidents,
        "release_gate": gate,
        "failures": [*(manifest.get("failures") or []), *retry_failures],
    }
    write_aggregate(run_dir / "aggregate.json", aggregate)
    (run_dir / "gold_issue_traces.json").write_text(json.dumps(traces, indent=2), encoding="utf-8")
    displayed = metrics if metrics is not None else provisional_metrics
    run_config = manifest.get("config") or {}
    quality_label = "confirmed-label" if metrics is not None else "PROVISIONAL source-label"
    actionable = displayed.get("actionable") or {}
    blocking = actionable.get("blocking_recall")
    blocking_text = "N/A" if blocking is None else f"{blocking:.1%}"
    def percent(value: Any) -> str:
        return "N/A" if value is None else f"{value:.1%}"
    latency = provisional_metrics.get("latency_seconds") or {}
    lines = [
        f"# CodeTurtle validation report — {split.name}", "",
        f"Reviewer commit: `{metadata.get('commit')}` (reviewer dirty: {metadata.get('reviewer_dirty')})",
        f"Model: `{run_config.get('model')}`; runtime: `{run_config.get('runtime')}`; bundle/step caps: `{run_config.get('bundle_max')}/{run_config.get('agent_max_steps')}`",
        f"Graphify package version: `{metadata.get('graphify_version', 'not recorded')}`; run started: `{manifest.get('started_at')}`",
        f"Split: **{split.split}**; headline eligible: **{split.eligible_for_headline_metrics}**",
        f"Dataset SHA-256: `{metadata.get('dataset_sha256')}`", "",
        f"Predictions: **{len(predictions)}/{len(split.prs)} PRs**; gold status: `{dict(label_counts)}`",
        f"Infrastructure incidents: **{len(incidents)}** (recovered: {sum(item['recovered_by_supplement'] for item in incidents)})",
        f"Confirmed known issues detected: **{confirmed_detected}/{confirmed_gold_count}** (issue recall only; not a precision estimate)",
        f"Scoring basis: **{quality_label}**; unscored PRs: **{len(unscored_prs)}**", "",
        f"TP / FP / FN: **{displayed.get('tp', 0)} / {displayed.get('fp', 0)} / {displayed.get('fn', 0)}**",
        f"Precision / recall / F1: **{percent(displayed.get('precision'))} / {percent(displayed.get('recall'))} / {percent(displayed.get('f1'))}**",
        f"FP per PR: **{displayed.get('fp_per_pr', 0):.2f}**",
        f"Blocking gold / detected / recall: **{actionable.get('blocking_gold_count', 0)} / {actionable.get('blocking_detected', 0)} / {blocking_text}**",
        f"Clean PRs: **{actionable.get('clean_pr_count', 0)}** (source benchmark contains no clean controls)",
        f"Median / p95 latency across all completed PRs: **{latency.get('p50', 0):.2f}s / {latency.get('p95', 0):.2f}s**", "",
        f"Decision accuracy across all completed PRs (provisional labels): **{(provisional_metrics.get('decision') or {}).get('accuracy', 0):.1%}**", "",
        "## False-negative attribution", "",
    ]
    lines.extend(f"- {stage}: {count}" for stage, count in sorted(confirmed_distribution.items()))
    if not confirmed_distribution:
        lines.append("- None in scored source labels")
    lines.append("")
    lines.append(f"Provisional source-label attribution: `{dict(distribution)}`")
    lines.extend([
        "", "## False positives", "",
        (f"{len(provisional_false_positives)} source-label unmatched findings; all require manual adjudication."
         if provisional_false_positives else "No findings were emitted. Zero observed false positives does not establish precision or clean-PR safety."),
        "", "## Release gate", "", render_gate(gate), "",
        "This is a small diagnostic run. Source-label matching and issue-stage links require manual audit;"
        " no clean-PR false-positive claim is supported.", "",
    ])
    (run_dir / "validation_report.md").write_text("\n".join(lines), encoding="utf-8")
    return aggregate


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--adjudications", required=True, type=Path)
    parser.add_argument("--supplement-run", action="append", type=Path, default=[])
    parser.add_argument("--failure-adjudications", type=Path)
    args = parser.parse_args()
    result = score_run(args.run_dir, args.adjudications, args.supplement_run, args.failure_adjudications)
    print(f"Split: {result['split_name']} ({result['split']})")
    print(f"Predicted: {result['prs_predicted']}/{result['prs_selected']} PRs")
    print(f"Label status: {result['label_counts']}")
    print(f"Confirmed known issues: {result['confirmed_known_issue_detection']['detected']}/{result['confirmed_known_issue_detection']['gold_count']}")
    if result["metrics"] is None:
        print("Confirmed-label metrics: N/A (no fully adjudicated PRs)")
    else:
        print(render_ascii(result["metrics"]))
    print("Provisional source-label metrics (not headline):")
    print(render_ascii(result["provisional_metrics"]))
    print(f"Confirmed FN attribution: {result['failure_attribution']}")
    print(f"Provisional FN attribution: {result['provisional_failure_attribution']}")
    print(render_gate(result["release_gate"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
