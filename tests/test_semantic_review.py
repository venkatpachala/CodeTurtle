"""Semantic safety controls use real pinned Git sources, never execute PR code."""
import json

import pytest
from pydantic import ValidationError

from core.agent.bundle_agent import BundleAgent
from core.agent.semantic import Outcome, RegressionLead, RegressionProof, validate_transition
from core.input.snapshot import GitSnapshotProvider
from core.input.tools import SnapshotBundleTools
from core.review.inspection import collect_inspection
from core.runtime.models import Bundle
from core.verification.diff_index import build_diff_index
from core.verification.literal_facts import contradicts_literal
from tests.test_input_snapshot import git


def unit(uid="CU-001", excerpt='-    method = "GET"\n+    method = "POST"'):
    return {"id": uid, "path": "app.py", "kind": "source", "start_line": 2, "excerpt": excerpt}


def assessment(uid="CU-001", regression=False):
    return {"unit_id": uid, "behavioral_delta": "Request method changed", "contract": "Use GET for reads",
            "contract_basis": "source_inference", "contract_reference": "read operation",
            "outcome": "potential_regression" if regression else "fix_consistent",
            "evidence_refs": [uid], "missing_evidence": [],
            "hypothesis": {"symbol": "request", "trigger": "read request",
                           "expected": outcome("GET"), "suspected": outcome("POST")} if regression else None}


def outcome(value):
    return {"kind": "literal", "property": "method", "value": value}


def proof_for(prompt, head_value="POST"):
    package = json.loads(prompt.split("\nPACKAGE\n", 1)[1])
    observed = {}
    for side, value in (("base", "GET"), ("head", head_value)):
        evidence = next(e for e in package["evidence"] if e["result"].get("source") == "git_snapshot"
                        and e["result"].get("side", "head") == side)
        observed[side] = {**outcome(value), "source": {"evidence_id": evidence["id"], "start_line": 2, "end_line": 2}}
    return {"conclusion": "violation_supported", "reason": "Changed method violates the read contract",
            **observed, "missing_evidence": []}


def pinned_tools(tmp_path, head="POST"):
    git(tmp_path, "init")
    git(tmp_path, "config", "user.name", "Semantic test")
    git(tmp_path, "config", "user.email", "test@example.invalid")
    (tmp_path / "app.py").write_text('def request():\n    method = "GET"\n    return method\n')
    git(tmp_path, "add", ".")
    git(tmp_path, "commit", "-m", "baseline")
    base = git(tmp_path, "rev-parse", "HEAD")
    (tmp_path / "app.py").write_text(f'def request():\n    method = "{head}"\n    return method\n')
    git(tmp_path, "commit", "--allow-empty", "-am", "head")
    provider = GitSnapshotProvider(tmp_path)
    snapshot = provider.resolve(base)
    bundle = Bundle(id="B-001", paths=["app.py"], units=[unit()])
    return bundle, SnapshotBundleTools(bundle, index=build_diff_index(provider.diff(snapshot)), provider=provider, snapshot=snapshot)


def test_fix_assessment_never_becomes_defect_candidate():
    bundle = Bundle(id="B1", paths=["app.py"], units=[unit()])
    result = BundleAgent(llm=lambda _: json.dumps({"assessments": [assessment()]}), discovery_protocol="semantic").run_result(bundle)
    assert result.status == "VALID_EMPTY"
    assert not result.hypotheses and not result.candidates
    assert result.contract_assessments[0]["verification_level"] == "source_assessment_not_execution"
    assert result.to_dict()["prompt_version"] == "semantic-contract-v4-scoped-authority"


def test_partial_assessment_repairs_only_missing_units_and_preserves_inspection():
    bundle = Bundle(id="B1", paths=["app.py"], units=[unit(), unit("CU-002")])
    prompts = []
    def respond(prompt):
        prompts.append(prompt)
        return json.dumps({"assessments": [assessment()]}) if len(prompts) == 1 else "invalid"
    result = BundleAgent(llm=respond, discovery_protocol="semantic").run_result(bundle)
    second = json.loads(prompts[1].split("\nPACKAGE\n")[1])
    assert [u["unit_id"] for u in second["units"]] == ["CU-002"]
    assert result.status == "PARTIAL"
    coverage = collect_inspection(bundle.units, [bundle], [{"bundle_id": bundle.id, **result.to_dict()}])
    assert coverage.inspected == 1
    assert coverage.assessments[1].reason == "assessment_unavailable"


@pytest.mark.parametrize("head,claimed,accepted", [("POST", "POST", True), ("GET", "POST", False), ("POST", "GET", False)])
def test_pinned_base_head_transition_and_contradiction_checks(tmp_path, head, claimed, accepted):
    bundle, tools = pinned_tools(tmp_path, head)
    calls = []
    def respond(prompt):
        calls.append(prompt)
        return json.dumps({"assessments": [assessment(regression=True)]}) if len(calls) == 1 else json.dumps(proof_for(prompt, claimed))
    result = BundleAgent(llm=respond, discovery_protocol="semantic").run_result(bundle, tools)
    assert bool(result.candidates) == accepted
    if accepted:
        candidate = result.candidates[0]
        assert candidate.existing_code == '    method = "POST"'
        assert candidate.verify_status == "candidate"  # Not independently verified by this stage.
        assert candidate.start_line == 2 and candidate.confidence == 0.5
    else:
        assert result.semantic_rejections and result.status == "PARTIAL"


@pytest.mark.parametrize("mutation", ["same_outcome", "wrong_side", "foreign_evidence", "outside_lines", "base_does_not_satisfy"])
def test_proof_cannot_invent_evidence_or_unchanged_regression(tmp_path, mutation):
    bundle, tools = pinned_tools(tmp_path)
    records = []
    for side in ("base", "head"):
        records.append({"id": side, "result": tools.read_source("app.py", symbol="request", side=side)})
    value = {"conclusion": "violation_supported", "reason": "read method changed", "missing_evidence": [],
             "base": {**outcome("GET"), "source": {"evidence_id": "base", "start_line": 2, "end_line": 2}},
             "head": {**outcome("POST"), "source": {"evidence_id": "head", "start_line": 2, "end_line": 2}}}
    if mutation == "same_outcome": value["head"]["value"] = "GET"
    if mutation == "wrong_side": value["head"]["source"]["evidence_id"] = "base"
    if mutation == "foreign_evidence": value["head"]["source"]["evidence_id"] = "invented"
    if mutation == "outside_lines": value["head"]["source"].update(start_line=999, end_line=999)
    if mutation == "base_does_not_satisfy": value["base"]["value"] = "POST"
    lead = RegressionLead.model_validate(assessment(regression=True)["hypothesis"])
    with pytest.raises(ValueError):
        validate_transition(RegressionProof.model_validate(value), lead, "app.py", records)


def test_regression_requires_distinct_expected_and_suspected_outcomes():
    lead = assessment(regression=True)["hypothesis"]
    lead["suspected"] = lead["expected"]
    with pytest.raises(ValidationError): RegressionLead.model_validate(lead)


def test_outcome_identity_preserves_empty_and_whitespace_sensitive_values():
    assert Outcome(**outcome("")).value == ""
    assert Outcome(**outcome("A  B")).identity != Outcome(**outcome("A B")).identity
    assert Outcome(**outcome(" GET ")).value == " GET "


def test_invalid_discovery_never_falls_back_to_legacy_protocol():
    result = BundleAgent(llm=lambda _: "[]", discovery_protocol="semantic").run_result(Bundle(id="B1", units=[unit()]))
    assert result.status == "INVALID_SCHEMA" and result.request_attempts == 2
    assert not result.candidates and result.discovery_protocol == "semantic-v1"


def test_unit_input_budget_is_visible_in_inspection():
    bundle = Bundle(id="B1", units=[unit(), unit("CU-002", "x" * 2501)])
    result = BundleAgent(llm=lambda _: json.dumps({"assessments": [assessment()]}), discovery_protocol="semantic").run_result(bundle)
    assert result.status == "PARTIAL"
    assert result.assessments[1]["reason"] == "model_input_budget"


def test_large_bundle_is_split_into_two_unit_requests():
    bundle = Bundle(id="B1", units=[unit(f"CU-{i:03d}") for i in range(1, 6)])
    packages = []
    def respond(prompt):
        package = json.loads(prompt.split("\nPACKAGE\n")[1])
        packages.append(package)
        return json.dumps({"assessments": [assessment(u["unit_id"]) for u in package["units"]]})
    result = BundleAgent(llm=respond, discovery_protocol="semantic").run_result(bundle)
    assert [len(p["units"]) for p in packages] == [2, 2]
    assert sum(a["status"] == "inspected" for a in result.assessments) == 4
    assert result.assessments[-1]["reason"] == "model_input_budget"
    assert result.status == "PARTIAL"


def test_truncated_batch_is_repaired_with_one_unit_instead_of_repeated():
    bundle = Bundle(id="B1", units=[unit(), unit("CU-002"), unit("CU-003")])
    packages = []
    agent = BundleAgent(discovery_protocol="semantic")
    def respond(prompt):
        package = json.loads(prompt.split("\nPACKAGE\n")[1])
        packages.append(package)
        agent.usage_records.append({"output_truncated": len(packages) == 1})
        return json.dumps({"assessments": [assessment(u["unit_id"]) for u in package["units"]]})
    agent.llm = respond
    result = agent.run_result(bundle)
    assert [[u["unit_id"] for u in p["units"]] for p in packages] == [["CU-001", "CU-002"], ["CU-001"], ["CU-002", "CU-003"]]
    assert result.status == "VALID_EMPTY" and len(result.protocol_errors) == 1


def test_repair_does_not_mix_missing_unit_with_next_batch():
    bundle = Bundle(id="B1", units=[unit(), unit("CU-002"), unit("CU-003")])
    ids = []
    def respond(prompt):
        package = json.loads(prompt.split("\nPACKAGE\n")[1])
        ids.append([u["unit_id"] for u in package["units"]])
        return json.dumps({"assessments": [assessment(uid) for uid in (ids[-1][:1] if len(ids) == 1 else ids[-1])]})
    result = BundleAgent(llm=respond, discovery_protocol="semantic").run_result(bundle)
    assert ids == [["CU-001", "CU-002"], ["CU-002"], ["CU-003"]]
    assert result.status == "VALID_EMPTY"


def test_failed_assessments_do_not_starve_remaining_units():
    bundle = Bundle(id="B1", units=[unit(), unit("CU-002"), unit("CU-003")])
    ids = []
    def respond(prompt):
        package = json.loads(prompt.split("\nPACKAGE\n")[1])
        ids.append([u["unit_id"] for u in package["units"]])
        return "invalid" if len(ids) < 3 else json.dumps({"assessments": [assessment("CU-003")]})
    result = BundleAgent(llm=respond, discovery_protocol="semantic").run_result(bundle)
    assert ids == [["CU-001", "CU-002"], ["CU-001", "CU-002"], ["CU-003"]]
    assert result.status == "PARTIAL" and result.assessments[-1]["status"] == "inspected"


@pytest.mark.parametrize("code,path,expected", [
    ('Request(method="GET")', "app.py", True), ('method="GET",', "app.py", False), ('method = get_method()', "app.py", False),
    ('method="GET"\nmethod="POST"', "app.py", False), ('let method = "GET";', "app.rs", False)])
def test_literal_checker_abstains_from_computed_or_ambiguous_values(code, path, expected):
    assert contradicts_literal(code, "method", "POST", path, "literal") is expected
