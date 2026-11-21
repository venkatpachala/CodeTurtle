"""Useful excerpts preserve location, completeness boundaries, and verifier gates."""
import hashlib
import json

import pytest

from core.domain.observations import SourceCitation, SourceObservation, observation_id
from core.input.excerpts import capture_excerpt
from core.intent.observations import collect_observations
from core.review.budget import ReviewBudget
from core.verification.source_verifier import SourceFindingVerifier
from tests.test_source_finding_verifier import candidate, PROTECTED, BROKEN, verification_case
from tests.test_input_snapshot import repository
from tests.test_input_snapshot import git


def test_complete_late_function_has_absolute_lines_and_declared_scope():
    source = "# unrelated module documentation\n" * 300 + PROTECTED
    excerpt = capture_excerpt(source, "app.py", symbol="size")
    assert excerpt.scope == "python_function" and excerpt.complete
    assert excerpt.start_line == 301 and not excerpt.unresolved_dependencies
    assert excerpt.text == PROTECTED.rstrip("\n")


@pytest.mark.parametrize("prefix,body,dependency", [
    ("", "    return external(items)\n", "external"),
    ("len = custom_len\n", "    return len(items)\n", "len"),
    ("from package import *\n", "    return len(items)\n", "wildcard module import"),
    ("", "    return items.method()\n", "attribute contract"),
    ("", "    global items\n    return len(items)\n", "dynamic or imported function bindings"),
])
def test_omitted_dependencies_do_not_become_complete_evidence(prefix, body, dependency):
    source = prefix + "# filler\n" * 300 + "def size(items):\n" + body
    excerpt = capture_excerpt(source, "app.py", symbol="size")
    assert excerpt.complete  # The function text is complete; its contracts are not.
    assert dependency in excerpt.unresolved_dependencies


def test_decorated_and_ambiguous_functions_remain_incomplete():
    source = "# filler\n" * 300 + "@decorate\n" + PROTECTED
    excerpt = capture_excerpt(source, "app.py", symbol="size")
    assert "function decorators" in excerpt.unresolved_dependencies
    duplicate = capture_excerpt(source + PROTECTED, "app.py", symbol="size", anchor=305)
    assert duplicate.scope == "window" and not duplicate.complete


def test_oversized_function_cannot_be_relabelled_as_complete():
    excerpt = capture_excerpt("def size(items):\n" + "    pass\n" * 300, "app.py", symbol="size")
    assert excerpt.scope == "window" and not excerpt.complete
    focused = capture_excerpt("def size(items):\n" + "    pass\n" * 300, "app.py", symbol="size", anchor=250)
    assert focused.start_line <= 250 < focused.start_line + len(focused.text.splitlines())


def decision(prompt, verdict="supported"):
    package = json.loads(prompt.split("\nPACKAGE\n", 1)[1])
    obs = package["head_observations"][0]
    citation = {"observation_id": obs["id"], "start_line": obs["start_line"],
        "end_line": obs["end_line"], "quote": obs["text"]}
    return json.dumps({"verdict": verdict, "checked_trigger": "items is None",
        "rationale": "The exact function body establishes this direct invocation behavior",
        "path_analysis": "size(None) reaches len or an earlier return",
        "supporting_citations": [citation] if verdict == "supported" else [],
        "counter_citations": [citation] if verdict == "refuted" else [], "missing_evidence": [],
        "refutation_basis": "head_guard" if verdict == "refuted" else "none"})


@pytest.mark.parametrize("after,verdict,outcome", [(BROKEN,"supported","VERIFIED"),(PROTECTED,"refuted","DISPROVED")])
def test_final_gate_uses_complete_late_function_and_keeps_citations_absolute(verification_case, after, verdict, outcome):
    prefix = "# filler\n" * 300
    provider, snapshot = verification_case(before=prefix+PROTECTED, after=prefix+after)
    verifier = SourceFindingVerifier(provider, snapshot, lambda p: decision(p, verdict), ReviewBudget())
    assert verifier.verify(candidate(), None, []) == outcome
    for observation in verifier.observations.values():
        assert observation.scope == "python_function" and observation.start_line == 301
        assert observation.status == "success"
    verifier.records[0].validate_sources(verifier.observations)


def test_external_dependency_prevents_final_model_admission(verification_case):
    source = "# filler\n" * 300 + "def size(items):\n    return external(items)\n"
    provider, snapshot = verification_case(before=source, after=source)
    verifier = SourceFindingVerifier(provider, snapshot, lambda _: pytest.fail("incomplete scope admitted"), ReviewBudget())
    assert verifier.verify(candidate(), None, []) == "UNCERTAIN"
    assert verifier.records[0].status == "context_unavailable"
    assert "external" in verifier.records[0].reason


def test_scope_and_absolute_position_are_part_of_observation_identity():
    original = observation_id("a"*64,"head","app.py","code","success")
    expected = "OBS-" + hashlib.sha256(json.dumps(["a"*64,"head","app.py","code","success"],separators=(",",":")).encode()).hexdigest()[:24]
    assert original == expected  # Historical whole-file identities are stable.
    assert original != observation_id("a"*64,"head","app.py","code","success",start_line=301,scope="python_function",symbol="size")


def test_two_hypotheses_in_same_file_receive_their_own_function_context(repository):
    from core.agent.bundle_agent import BundleAgent
    from core.agent.hypothesis import ReviewHypothesis
    from core.input.snapshot import GitSnapshotProvider
    from core.input.tools import SnapshotBundleTools
    from core.runtime.models import Bundle
    from core.verification.diff_index import build_diff_index
    root, base = repository
    (root / "app.py").write_text(PROTECTED + "# filler\n" * 300 + "def total(values):\n    return sum(values)\n")
    git(root,"commit","-am","separate functions")
    provider = GitSnapshotProvider(root)
    snapshot = provider.resolve(base)
    tools = SnapshotBundleTools(Bundle(id="B1", paths=["app.py"]), index=build_diff_index(provider.diff(snapshot)),
                                provider=provider, snapshot=snapshot)
    hyps = [ReviewHypothesis(id=f"H{n}",bundle_id="B1",file="app.py",symbol=symbol,
        observation="changed function",hypothesis="check behavior",required_evidence=["source"])
        for n,symbol in enumerate(("size","total"))]
    calls = []
    BundleAgent()._collect_evidence(hyps, tools, calls)
    sources = [call["result"] for call in calls if call["request"]["tool"] == "read_source"]
    assert [item["scope_symbol"] for item in sources] == ["size", "total"]
    assert sources[1]["start_line"] == 305
