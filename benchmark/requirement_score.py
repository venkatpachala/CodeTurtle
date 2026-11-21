"""Score sealed synthetic requirement outcomes; never claim real-PR precision/recall."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from core.review.artifacts import write_json_atomic
from core.runtime.models import ReviewResult


def score_experiment(directory: Path, corpus: Path) -> dict:
    metadata = json.loads((directory / "manifest.json").read_text())
    seal = json.loads((directory / "seal.json").read_text())
    for name, field in (("predictions.json", "predictions_sha256"), ("manifest.json", "manifest_sha256")):
        if hashlib.sha256((directory / name).read_bytes()).hexdigest() != seal[field]:
            raise ValueError("sealed experiment integrity mismatch")
    labels_bytes = (corpus / "labels.json").read_bytes()
    if hashlib.sha256(labels_bytes).hexdigest() != metadata["corpus"]["labels_sha256"]:
        raise ValueError("annotation integrity mismatch")
    labels = {(item["case_id"], item["requirement_id"]): item for item in json.loads(labels_bytes)}
    predictions = json.loads((directory / "predictions.json").read_text())
    if (len(predictions) != seal["prediction_count"]
            or len(predictions) != metadata["case_count"] * len(metadata["strategies"])):
        raise ValueError("prediction count mismatch")
    report = {"scope": metadata["scope"], "eligible_for_headline_metrics": False,
              "precision": None, "recall": None, "strategies": {}, "cases": [],
              "limitations": ["Author-labelled synthetic development cases; not held-out or independent adjudication.",
                              "Requirement outcome matches do not establish general defect-detection accuracy.",
                              "Local model tags are recorded, not immutable model artifact digests."]}
    seen, paired = set(), {}
    for prediction in predictions:
        identity = (prediction["case_id"], prediction["strategy"])
        if prediction["strategy"] not in metadata["strategies"]:
            raise ValueError("unexpected strategy")
        if identity in seen:
            raise ValueError("duplicate case/strategy prediction")
        seen.add(identity)
        result = ReviewResult.from_dict(prediction["result"])
        expected_requirements = {requirement for case, requirement in labels if case == prediction["case_id"]}
        if not expected_requirements or {item.requirement_id for item in result.requirement_assessments} != expected_requirements:
            raise ValueError("missing or unknown requirement assessment")
        source = (prediction["source_case_sha256"], result.provenance["source_input_id"])
        if paired.setdefault(prediction["case_id"], source) != source:
            raise ValueError("paired strategies used different source input")
        row = report["strategies"].setdefault(prediction["strategy"],
            {"reviews": 0, "completed": 0, "requirement_outcomes": 0, "matching_outcomes": 0,
             "actual_model_calls": 0, "reported_prompt_tokens": 0, "reported_completion_tokens": 0,
             "calls_missing_usage": 0, "model_call_errors": 0})
        row["reviews"] += 1
        row["completed"] += int(result.health.status == "completed")
        for call in result.provenance["model_calls"]:
            row["actual_model_calls"] += 1
            row["model_call_errors"] += int(call.get("status") != "success")
            if call.get("prompt_tokens") is None or call.get("completion_tokens") is None:
                row["calls_missing_usage"] += 1
            else:
                row["reported_prompt_tokens"] += call["prompt_tokens"]
                row["reported_completion_tokens"] += call["completion_tokens"]
        for assessment in result.requirement_assessments:
            label = labels[(prediction["case_id"], assessment.requirement_id)]
            matched = assessment.status == label["expected_status"]
            row["requirement_outcomes"] += 1
            row["matching_outcomes"] += int(matched)
            report["cases"].append({"case_id": prediction["case_id"], "strategy": prediction["strategy"],
                "expected_status": label["expected_status"], "actual_status": assessment.status,
                "matches_label": matched, "health": result.health.status,
                "findings": len(result.product_findings), "elapsed_seconds": prediction["elapsed_seconds"]})
    for case_id in paired:
        if {strategy for case, strategy in seen if case == case_id} != set(metadata["strategies"]):
            raise ValueError("incomplete paired strategy membership")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--corpus", type=Path, default=Path("benchmark/datasets/requirement_development_v1"))
    args = parser.parse_args()
    report = score_experiment(args.directory, args.corpus)
    write_json_atomic(args.directory / "score.json", report)
    print(json.dumps(report["strategies"], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
