"""Negated or conflicting verdict text cannot promote an uncertain claim."""
import pytest

from core.runtime.models import Candidate
from core.runtime.verify_loop import _falsify_llm


@pytest.mark.parametrize("answer", [
    "This is not VERIFIED", "Not VERIFIED", "VERIFIED, but actually UNCERTAIN",
    "DISPROVED or VERIFIED", "", "No conclusion",
])
def test_ambiguous_verdicts_are_uncertain(answer):
    candidate = Candidate(bundle_id="B1", file="app.py")
    assert _falsify_llm(candidate, lambda _: answer, "+return value") == "UNCERTAIN"


@pytest.mark.parametrize("answer,status", [
    ("VERIFIED", "VERIFIED"), ("DISPROVED: protected downstream", "DISPROVED"),
    ("UNCERTAIN missing database policy", "UNCERTAIN"),
])
def test_explicit_leading_verdicts_are_accepted(answer, status):
    candidate = Candidate(bundle_id="B1", file="app.py")
    assert _falsify_llm(candidate, lambda _: answer, "+return value") == status
