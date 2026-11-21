"""Prediction sealing, input-only operation, paired identity, and honest scoring."""
import json
from pathlib import Path
import shutil

import pytest

from benchmark.requirement_experiment import run_experiment
from benchmark.requirement_score import score_experiment

CORPUS = Path(__file__).resolve().parents[1] / "benchmark/datasets/requirement_development_v1"


class ScriptedProvider:
    def __init__(self):
        self.calls = []
    def generate(self, stage, prompt, max_tokens=1400):
        self.calls.append({"stage": stage, "status": "success", "prompt_tokens": 0, "completion_tokens": 0})
        if stage == "discovery":
            return "[]"
        if stage == "finding_or_link_verifier":
            return "UNVERIFIED"
        package = json.loads(prompt.split("\nPACKAGE\n", 1)[1])
        return json.dumps({"requirement_id": package["requirement"]["id"], "outcome": "unresolved",
            "rationale": "Scripted integration provider; not real reasoning", "checked_scope": "fixture",
            "citations": [], "counterevidence": [], "missing_evidence": ["not evaluated by a real model"]})


@pytest.fixture
def experiment(tmp_path):
    destination = tmp_path / "run"
    run_experiment(CORPUS, destination, ScriptedProvider(), model="scripted-test", limit=2)
    return destination


def test_prediction_does_not_load_labels_and_cannot_overwrite_runs(tmp_path):
    corpus = tmp_path / "inputs-only"
    corpus.mkdir()
    for name in ("manifest.json", "inputs.json"):
        shutil.copyfile(CORPUS / name, corpus / name)
    output = tmp_path / "run"
    run_experiment(corpus, output, ScriptedProvider(), model="scripted-test", limit=1)
    assert (output / "seal.json").exists()
    with pytest.raises(FileExistsError):
        run_experiment(corpus, output, ScriptedProvider(), model="scripted-test", limit=1)


def test_scoring_reports_all_outcomes_and_keeps_headline_metrics_undefined(experiment):
    report = score_experiment(experiment, CORPUS)
    assert report["eligible_for_headline_metrics"] is False
    assert report["precision"] is report["recall"] is None
    assert report["strategies"]["investigate"]["reviews"] == 2
    assert report["strategies"]["investigate"]["requirement_outcomes"] == 2
    assert report["strategies"]["investigate"]["matching_outcomes"] == 0
    assert len(report["cases"]) == 4


def test_modified_predictions_or_annotations_are_rejected(experiment, tmp_path):
    path = experiment / "predictions.json"
    original = path.read_bytes()
    path.write_text("[]")
    with pytest.raises(ValueError, match="integrity"):
        score_experiment(experiment, CORPUS)
    path.write_bytes(original)
    corpus = tmp_path / "labels"
    corpus.mkdir()
    (corpus / "labels.json").write_text("[]")
    with pytest.raises(ValueError, match="annotation integrity"):
        score_experiment(experiment, corpus)
