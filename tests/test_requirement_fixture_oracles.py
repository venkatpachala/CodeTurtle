"""Check observable behavior of trusted authored fixtures, not arbitrary PR code.

These probes validate the development labels; they are not an independent corpus
or a sandbox. Prediction and scoring still never execute supplied review inputs.
"""
import json
from pathlib import Path
import subprocess
import sys

import pytest

from benchmark.requirement_corpus import load_corpus

CORPUS = Path(__file__).resolve().parents[1] / "benchmark/datasets/requirement_development_v1"

PROBE = """
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path.cwd()))
import app
if hasattr(app, 'size'):
    try:
        outcome = {'result': app.size(None)}
    except TypeError:
        outcome = {'exception': 'TypeError'}
else:
    document = {'tenant': 'own'}
    outcome = {'own_visible': app.document(document, 'own') == document,
               'other_visible': app.document(document, 'other') is not None}
print(json.dumps(outcome))
"""


@pytest.mark.parametrize("case_id,expected", [
    ("none-guard-removed", ({"result": 0}, {"exception": "TypeError"})),
    ("none-guard-preserved", ({"result": 0}, {"result": 0})),
    ("tenant-filter-removed", ({"own_visible": True, "other_visible": False},
                               {"own_visible": True, "other_visible": True})),
    ("tenant-guard-delegated", ({"own_visible": True, "other_visible": False},
                                {"own_visible": True, "other_visible": False})),
])
def test_selected_development_labels_match_observable_base_head_behavior(tmp_path, case_id, expected):
    _, cases = load_corpus(CORPUS)  # Checks the committed input hash before execution.
    case = next(item for item in cases if item.case_id == case_id)
    for side, oracle in zip(("base", "head"), expected):
        root = tmp_path / side
        root.mkdir()
        for path, versions in case.files.items():
            content = getattr(versions, side)
            if content is not None:
                destination = root / path
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_text(content, encoding="utf-8", newline="\n")
        result = subprocess.run([sys.executable, "-I", "-c", PROBE], cwd=root,
                                capture_output=True, text=True, timeout=10, check=True)
        assert json.loads(result.stdout) == oracle
