"""Preserve the outer object when an unfenced response contains multiple lists."""
import json

import pytest

from core.agent.parse import parse_agent_document, parse_agent_output


def test_unfenced_discovery_object_keeps_assessments_and_hypotheses():
    document = {"assessments": [{"unit_id": "CU-001"}], "hypotheses": []}
    assert parse_agent_document(json.dumps(document)) == document
    assert parse_agent_output(json.dumps(document)) == ("candidates", [])


def test_unfenced_proof_object_keeps_candidates_and_outcomes():
    document = {"candidates": [], "outcomes": [{"hypothesis_id": "H1", "status": "unresolved"}]}
    assert parse_agent_document("Result: " + json.dumps(document) + "\nDone.") == document


def test_truncated_outer_object_is_not_repaired_by_extracting_an_inner_list():
    raw = '{"candidates": [], "outcomes": ['
    assert parse_agent_output(raw) == ("invalid", None)
    with pytest.raises(ValueError):
        parse_agent_document(raw)
