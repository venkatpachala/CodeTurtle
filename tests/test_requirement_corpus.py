"""Frozen synthetic development inputs remain separate from scoring annotations."""
import json
from pathlib import Path
import shutil

import pytest

from benchmark.requirement_corpus import RequirementCase, load_corpus

ROOT = Path(__file__).resolve().parents[1] / "benchmark/datasets/requirement_development_v1"


def test_twelve_development_cases_have_explicit_scope_and_separate_annotations():
    manifest, cases = load_corpus(ROOT)
    assert len(cases) == 12
    assert manifest["eligible_for_headline_metrics"] is False
    assert all("expected_status" not in case.model_dump() for case in cases)
    labels = json.loads((ROOT / "labels.json").read_text())
    assert {case.case_id for case in cases} == {label["case_id"] for label in labels}
    assert {label["category"] for label in labels} == {"defect", "clean", "unresolved"}


def test_prediction_loader_does_not_need_annotation_file(tmp_path):
    for name in ("manifest.json", "inputs.json"):
        shutil.copyfile(ROOT / name, tmp_path / name)
    assert len(load_corpus(tmp_path)[1]) == 12


def test_changed_inputs_are_rejected(tmp_path):
    shutil.copytree(ROOT, tmp_path / "corpus")
    (tmp_path / "corpus/inputs.json").write_text("[]")
    with pytest.raises(ValueError, match="integrity"):
        load_corpus(tmp_path / "corpus")


def test_fixtures_cannot_overwrite_git_configuration():
    with pytest.raises(ValueError, match="Git control"):
        RequirementCase(case_id="bad", files={".git/config": {"base": None, "head": "bad"}},
                        requirements=[{"id": "R1", "description": "Rule", "acceptance_criterion": "Rule", "paths": ["app.py"]}])
