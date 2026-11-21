"""Synthetic fixture files cannot be mistaken for registered real-PR splits."""
from pathlib import Path

import pytest

from benchmark.splits import load_registered_splits, load_split


def test_registered_pr_splits_exclude_synthetic_requirement_fixtures():
    root = Path(__file__).resolve().parents[1] / "benchmark/datasets"
    splits = load_registered_splits(root)
    assert splits
    assert all(split.path.parent.name in {"development", "validation", "test"} for split in splits)


def test_list_input_is_rejected_with_a_manifest_error(tmp_path):
    path = tmp_path / "inputs.json"
    path.write_text("[]")
    with pytest.raises(ValueError, match="JSON object"):
        load_split(path)
