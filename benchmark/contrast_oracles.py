"""Evaluate sealed synthetic predictions against trusted, isolated BASE/HEAD probes."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import tempfile

from benchmark.requirement_corpus import load_corpus
from benchmark.requirement_experiment import materialize_case
from core.input.snapshot import GitSnapshotProvider
from core.review.artifacts import write_json_atomic
from core.review.isolated import DockerRunner, IsolationProfile


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_sealed_predictions(experiment: Path, manifest: dict, case_ids: set[str]) -> dict:
    seal = json.loads((experiment / "seal.json").read_bytes())
    for name, field in (("predictions.json", "predictions_sha256"),
                        ("manifest.json", "manifest_sha256"),
                        ("matched-reference-inputs.json", "reference_inputs_sha256")):
        if _sha256(experiment / name) != seal[field]:
            raise ValueError(f"sealed artifact changed: {name}")
    if json.loads((experiment / "manifest.json").read_bytes())["corpus"] != manifest:
        raise ValueError("sealed predictions belong to a different corpus")
    rows = json.loads((experiment / "predictions.json").read_bytes())
    indexed = {row["case_id"]: row for row in rows}
    if len(rows) != seal["prediction_count"] or len(indexed) != len(rows) or set(indexed) != case_ids:
        raise ValueError("sealed predictions do not cover the corpus exactly once")
    return indexed


def evaluate(corpus: Path, experiment: Path, output: Path, runner: DockerRunner) -> dict:
    manifest, cases = load_corpus(corpus)
    predictions = load_sealed_predictions(experiment, manifest, {case.case_id for case in cases})
    if _sha256(corpus / "labels.json") != manifest["labels_sha256"]:
        raise ValueError("oracle labels changed")
    labels = json.loads((corpus / "labels.json").read_bytes())
    reports = []
    for case in cases:
        label = labels[case.case_id]
        with tempfile.TemporaryDirectory(prefix="ct-oracle-") as directory:
            root = Path(directory)
            base, _ = materialize_case(root, case)
            provider = GitSnapshotProvider(root)
            snapshot = provider.resolve(base)
            command = ["python", "-c", label["probe"]]
            runs = {side: runner.run(provider, snapshot, command, side=side) for side in ("base", "head")}
        matches = all(
            run["status"] == "passed" if label[f"expected_{side}_passes"]
            else run["status"] == "failed" and run["output"].rstrip().splitlines()[-1:] == ["AssertionError"]
            for side, run in runs.items()
        )
        pred = predictions[case.case_id]
        result = pred["result"]
        sources = {}
        for path, versions in case.files.items():
            sources[path] = {
                side: hashlib.sha256(source.encode()).hexdigest() if source is not None else None
                for side, source in versions.model_dump().items()
            }
        reports.append({
            "case_id": case.case_id, "family_id": label["family_id"],
            "introduced_defect": label["introduced_defect"], "oracle_matches_label": matches,
            "runs": runs, "product_findings": len(result["product_findings"]),
            "decision": result["decision"], "latency_seconds": pred["elapsed_seconds"],
            "model_calls": result["provenance"]["budget"]["calls"],
            "completion_tokens": sum(call.get("completion_tokens") or 0 for call in result["provenance"]["model_calls"]),
            "source_file_digests": sources,
        })
    positives = [r for r in reports if r["introduced_defect"]]
    negatives = [r for r in reports if not r["introduced_defect"]]
    confirmed = bool(reports) and all(r["oracle_matches_label"] for r in reports)
    report = {
        "scope": "Synthetic development cases. Detection counts any finding on a case; issue identity needs a separate audit.",
        "predictions_sha256": _sha256(experiment / "predictions.json"),
        "all_oracles_passed": confirmed,
        "defect_cases_detected": sum(r["product_findings"] > 0 for r in positives) if confirmed else None,
        "defect_cases": len(positives),
        "repair_cases_with_findings": sum(r["product_findings"] > 0 for r in negatives) if confirmed else None,
        "repair_cases": len(negatives), "monetary_cost_usd": None, "cases": reports,
    }
    write_json_atomic(output, report)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--experiment", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--docker", default="docker")
    parser.add_argument("--image", required=True)
    parser.add_argument("--staging-root", type=Path)
    args = parser.parse_args()
    runner = DockerRunner(IsolationProfile(image=args.image), executable=args.docker, staging_root=args.staging_root)
    report = evaluate(args.corpus, args.experiment, args.output, runner)
    print(json.dumps({k: v for k, v in report.items() if k != "cases"}))
    raise SystemExit(0 if report["all_oracles_passed"] else 1)
