"""Real contract, parser, filesystem, Git, and subprocess tests; no doubles."""
from __future__ import annotations

import hashlib
import io
import json
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import pytest
from pydantic import ValidationError
from rich.console import Console

from benchmark.adapter import review_result_to_benchmark_review
from benchmark.evaluator import evaluate_pr
from benchmark.frozen import FrozenCase, validate_partitions, verify_case, seal_predictions
from benchmark.product_metrics import product_metrics, compare_regressions
from core.review.artifacts import write_json_atomic
from core.review.contract import ReviewCoverage, ReviewHealth, ReviewTarget, UnitAssessment, evaluate_policy
from core.review.finding import ReviewFinding
from core.review.inspection import collect_inspection, unresolved_hypotheses
from core.runtime.models import Bundle, Candidate, ReviewResult
from core.runtime.review_runtime import result_to_review_state
from core.output.publication import build_publication_plan, deliver_review
from core.output.terminal import render_findings_terminal
from core.verification.execute import _run_cmd
from core.workspace import clone_url, ensure_checkout, WorkspaceError


DIFF = "diff --git a/app.py b/app.py\n--- a/app.py\n+++ b/app.py\n@@ -1 +1 @@\n-limit = settings.limit\n+limit = 10\n"


def finding(**changes) -> ReviewFinding:
    return replace(ReviewFinding(id="F-001", title="Limit ignores configuration", claim="Configured limit is ignored",
        file="app.py", line=1, severity="medium", verification_status="verified", blocking=True,
        existing_code="limit = 10", invariant="Use configured limit", violating_condition="Configured limit is 20",
        expected="20", actual="10", execution_path=["load_limit"], evidence=["app.py"]), **changes)


def result(**changes) -> ReviewResult:
    return replace(ReviewResult(decision="REQUEST_CHANGES", findings=[finding()],
        target=ReviewTarget(repo="owner/repo", number=1, head_sha="a" * 40, base_sha="b" * 40,
                           diff_sha256=hashlib.sha256(DIFF.encode()).hexdigest()),
        health=ReviewHealth(status="completed"), inspection=ReviewCoverage(eligible=1, packed=1, inspected=1),
        policy_reasons=["verified_blocker"]), **changes)


@pytest.mark.parametrize("status,expected", [("completed", "MERGE"), ("partial", "COMMENT"), ("failed", None), ("skipped", None)])
def test_health_verdict(status, expected):
    outcome = evaluate_policy(health=ReviewHealth(status=status), coverage=ReviewCoverage(eligible=1, packed=1, inspected=1),
                              findings=[], unresolved=[], execution={})
    assert outcome.decision == expected


@pytest.mark.parametrize("eligible,packed,inspected", [(1, 1, 0), (2, 1, 1), (0, 0, 0)])
def test_inspection_abstains(eligible, packed, inspected):
    outcome = evaluate_policy(health=ReviewHealth(status="completed"),
        coverage=ReviewCoverage(eligible=eligible, packed=packed, inspected=inspected), findings=[], unresolved=[], execution={})
    assert outcome.decision == "COMMENT" and not outcome.approval_eligible


@pytest.mark.parametrize("execution", [{"skipped": False, "exit_code": 1, "failed": 1},
    {"skipped": True, "skip_reason": "timeout"}, {"python": {"skipped": False, "exit_code": 1}}])
def test_unattributed_execution_never_blocks(execution):
    outcome = evaluate_policy(health=ReviewHealth(status="completed"), coverage=ReviewCoverage(eligible=1, packed=1, inspected=1),
        findings=[], unresolved=[], execution=execution)
    assert outcome.decision == "COMMENT"


def test_blocker_survives_partial_analysis():
    assert evaluate_policy(health=ReviewHealth(status="partial"), coverage=ReviewCoverage(),
        findings=[finding()], unresolved=[{"reason": "missing_context"}], execution={}).decision == "REQUEST_CHANGES"


def test_uncertain_is_not_product_output():
    review = result(findings=[finding(verification_status="uncertain")])
    assert review.product_findings == []
    assert review_result_to_benchmark_review(review).review_comments == []
    assert evaluate_policy(health=review.health, coverage=review.inspection,
        findings=review.findings, unresolved=[], execution={}).decision == "COMMENT"


def test_canonical_empty_does_not_reconstruct_comments():
    from core.runtime.models import Comment
    state = result_to_review_state(result(findings=[], comments=[Comment(bundle_id="B1", file="app.py", title="legacy")]))
    assert state["findings"] == []


def test_fingerprint_excludes_run_identity():
    assert finding().fingerprint == finding(id="F-999", title="Different phrasing").fingerprint
    assert finding().fingerprint != finding(actual="30").fingerprint


@pytest.mark.parametrize("counts", [(1, 2, 0), (1, 1, 2), (-1, 0, 0)])
def test_invalid_coverage_rejected(counts):
    with pytest.raises(ValidationError):
        ReviewCoverage(eligible=counts[0], packed=counts[1], inspected=counts[2])


def test_inspection_needs_auditable_assessment():
    with pytest.raises(ValidationError):
        UnitAssessment(unit_id="u1", path="app.py", status="inspected")
    units = [{"id": "u1", "path": "app.py", "kind": "source", "excerpt": "+limit = 10"}]
    bundle = Bundle(id="b1", paths=["app.py"], units=units)
    run = {"bundle_id": "b1", "status": "VALID_EMPTY", "assessments": [
        {"unit_id": "u1", "behavioral_delta": "limit changed", "hypothesis_outcome": "no reachable consumer", "evidence_refs": ["u1"]}]}
    assert collect_inspection(units, [bundle], [run]).inspected == 1
    assert collect_inspection(units, [bundle], []).inspected == 0
    run["status"] = "INVALID_JSON"
    assert collect_inspection(units, [bundle], [run]).inspected == 0


def test_unproven_hypothesis_never_becomes_clean():
    run = {"bundle_id": "b1", "hypotheses": [{"id": "H1", "file": "app.py"}]}
    assert unresolved_hypotheses([run], [], [])[0]["reason"] == "proof_not_substantiated"


def test_preview_json_terminal_benchmark_agree():
    review = result()
    plan = build_publication_plan(review, full_diff=DIFF)
    data = json.loads(json.dumps(review.to_dict()))
    benchmark = review_result_to_benchmark_review(review).to_dict()
    stream = io.StringIO()
    render_findings_terminal(review.product_findings, console=Console(file=stream, width=140, color_system=None))
    assert data["product_findings"][0]["claim"] in plan.body
    assert data["product_findings"][0]["claim"] in stream.getvalue()
    assert benchmark["review_comments"][0]["path"] == plan.comments[0]["path"] == "app.py"
    assert plan.comments[0]["side"] == "RIGHT"


def test_merge_is_comment_without_explicit_approval():
    review = result(decision="MERGE", findings=[], approval_eligible=True)
    assert build_publication_plan(review, full_diff=DIFF).event == "COMMENT"
    assert build_publication_plan(review, full_diff=DIFF, approve=True).event == "APPROVE"


@pytest.mark.parametrize("change", ["failed", "sha", "diff", "approval"])
def test_bad_publication_plan_rejected(change):
    review = result()
    if change == "failed": review.health = ReviewHealth(status="failed")
    if change == "sha": review.target = review.target.model_copy(update={"head_sha": ""})
    with pytest.raises(ValueError):
        build_publication_plan(review, full_diff="bad" if change == "diff" else DIFF, approve=change == "approval")


def test_unanchorable_verified_finding_kept_in_summary():
    review = result(findings=[finding(line=None)])
    plan = build_publication_plan(review, full_diff=DIFF)
    assert plan.comments == [] and plan.summary_only_findings == ["F-001"]
    assert finding().claim in plan.body


def test_dry_delivery_requires_no_network():
    # No fabricated GitHub client: dry-run deliberately needs no client.
    plan = build_publication_plan(result(), full_diff=DIFF)
    assert deliver_review(None, plan).status == "dry_run"
    assert deliver_review(None, plan, dry_run=False).error_code == "publisher_identity_missing"


def test_atomic_json_real_filesystem(tmp_path):
    path = tmp_path / "result.json"
    write_json_atomic(path, result().to_dict())
    assert json.loads(path.read_text())["schema_version"] == "2.0"
    with pytest.raises(ValueError): write_json_atomic(path, {"invalid": float("nan")})
    assert json.loads(path.read_text())["schema_version"] == "2.0"
    assert len(list(tmp_path.iterdir())) == 1


def test_real_subprocess_does_not_inherit_credentials(tmp_path):
    proc = _run_cmd([sys.executable, "-c", "import os,json; print(json.dumps(sorted(os.environ)))"], tmp_path, 10, subprocess.run)
    names = json.loads(proc.stdout)
    assert proc.returncode == 0
    assert not any("TOKEN" in k or "API_KEY" in k or k.startswith("GIT_CONFIG") for k in names)
    assert "PYTEST_DISABLE_PLUGIN_AUTOLOAD" in names


def test_actual_pytest_subprocess(tmp_path):
    (tmp_path / "test_real.py").write_text("def test_arithmetic():\n    assert 2 + 2 == 4\n")
    proc = _run_cmd([sys.executable, "-m", "pytest", "test_real.py", "-q", "-p", "no:cacheprovider"], tmp_path, 30, subprocess.run)
    assert proc.returncode == 0 and "1 passed" in proc.stdout


def test_git_diff_and_sha_real_repository(tmp_path):
    def git(*args):
        return subprocess.run(["git", "-C", str(tmp_path), *args], check=True, capture_output=True, text=True).stdout.strip()
    git("init")
    git("config", "user.name", "CodeTurtle validation")
    git("config", "user.email", "validation@example.invalid")
    source = tmp_path / "app.py"
    source.write_text("limit = settings.limit\n")
    git("add", "app.py")
    git("commit", "-m", "base")
    base = git("rev-parse", "HEAD")
    source.write_text("limit = 10\n")
    git("commit", "-am", "head")
    head = git("rev-parse", "HEAD")
    diff = git("diff", base, head)
    assert base != head and "+limit = 10" in diff
    assert "token" not in clone_url("owner/repo", token="token")
    with pytest.raises(WorkspaceError): clone_url("../bad")


def test_frozen_inputs_and_lineage(tmp_path):
    (tmp_path / "diff.txt").write_bytes(DIFF.encode("utf-8"))
    digest = hashlib.sha256((tmp_path / "diff.txt").read_bytes()).hexdigest()
    case = FrozenCase(case_id="c1", repo="a/b", number=1, base_sha="b" * 40, head_sha="a" * 40,
        diff_file="diff.txt", diff_sha256=digest, lineage_id="bug1", split="development")
    assert verify_case(case, tmp_path) == DIFF
    other = case.model_copy(update={"number": 2, "split": "test"})
    with pytest.raises(ValueError): validate_partitions([case, other])
    (tmp_path / "diff.txt").write_text("tampered")
    with pytest.raises(ValueError): verify_case(case, tmp_path)
    seal_predictions(tmp_path / "sealed.json", [])
    with pytest.raises(FileExistsError): seal_predictions(tmp_path / "sealed.json", [])


def test_empty_product_output_cannot_fall_back_to_diagnostics():
    prediction = {"review_comments": [], "findings": [{"file": "app.py", "claim": "configuration limit ignored"}]}
    # The evaluator uses the actual product list, even when empty.
    score = evaluate_pr(prediction, [{"path": "app.py", "body": "configuration limit ignored"}])
    assert score["tp"] == 0


def test_product_metrics_and_regressions():
    metrics = product_metrics([])
    assert metrics["completion"]["value"] is None
    assert not compare_regressions({"p1": {"confirmed_issue_ids": ["g1"]}},
        {"p1": {"confirmed_issue_ids": [], "known_buggy": True, "decision": "MERGE"}})["passed"]


def test_fenced_document_preserves_assessments():
    from core.agent.parse import parse_agent_document
    document = {"assessments": [{"unit_id": "CU-001"}], "hypotheses": []}
    assert parse_agent_document("```json\n" + json.dumps(document) + "\n```") == document


def test_line_one_is_a_valid_anchor():
    from core.positioner import position_candidate
    from core.verification.diff_index import build_diff_index
    assert position_candidate(Candidate(bundle_id="B1", file="app.py", existing_code="limit = 10"), build_diff_index(DIFF)) == 1


def test_budget_has_hard_call_and_prompt_limits():
    from core.review.budget import ReviewBudget, BudgetExceeded
    budget = ReviewBudget(max_model_calls=1, max_prompt_chars=10)
    budget.reserve("abc")
    with pytest.raises(BudgetExceeded): budget.reserve("def")
    with pytest.raises(BudgetExceeded): ReviewBudget(max_prompt_chars=1).reserve("abc")
    with pytest.raises(BudgetExceeded): ReviewBudget(max_wall_seconds=0).reserve("abc")


def test_repository_lease_real_process(tmp_path):
    from core.review.lease import repository_lease
    command = [sys.executable, "-c",
        "from pathlib import Path; from core.review.lease import repository_lease; "
        f"lease=repository_lease('a/b',Path({str(tmp_path)!r}),timeout=0); lease.__enter__(); lease.__exit__(None,None,None)"]
    with repository_lease("a/b", tmp_path):
        blocked = subprocess.run(command, capture_output=True, text=True, timeout=15)
        assert blocked.returncode != 0 and "TimeoutError" in blocked.stderr
    released = subprocess.run(command, capture_output=True, text=True, timeout=15)
    assert released.returncode == 0


def test_source_retrieval_real_checkout(tmp_path):
    from core.agent.tools import BundleTools
    (tmp_path / "app.py").write_text("def divide(total, count):\n    return total / count\n")
    tools = BundleTools(Bundle(id="b1", paths=["app.py"]), repo_dir=str(tmp_path))
    assert "return total / count" in tools.read_source("app.py")["text"]
    assert tools.read_source("../outside.py").get("error")
    ambiguous = BundleTools(Bundle(id="b1", paths=["a/app.py", "b/app.py"]))
    assert ambiguous._in_bundle("app.py") is None


def test_missing_metric_denominators_are_unmeasured():
    from benchmark.metrics import aggregate_metrics
    from benchmark.reports import render_ascii
    from benchmark.gates import evaluate_release_gate
    metrics = aggregate_metrics([])
    assert metrics["agent_run_success_rate"] is None
    assert "N/A" in render_ascii(metrics)
    assert evaluate_release_gate(metrics, {})["checks"]["latency"] is None


def test_unfrozen_release_cannot_pass():
    from benchmark.release import evaluate_paired_release
    assert not evaluate_paired_release({}, {})["passed"]


def test_workflows_parse_and_pin_real_actions():
    import re
    import yaml
    root = Path(__file__).resolve().parents[1]
    for relative in ("examples/github-action.yml", ".github/workflows/codeturtle-review.yml", ".github/workflows/production-validation.yml"):
        workflow = yaml.load((root / relative).read_text(), Loader=yaml.BaseLoader)
        assert "on" in workflow and "jobs" in workflow
        for job in workflow["jobs"].values():
            for step in job["steps"]:
                if "uses" in step:
                    assert re.fullmatch(r"actions/[a-z-]+@[0-9a-f]{40}", step["uses"])
    assert "codeturrle" not in (root / "examples/github-action.yml").read_text()


def test_anonymous_auth_context_restores_real_environment():
    import os
    from core.ci import github_authentication, resolve_github_token
    before = os.environ.get("CODETURTLE_ANONYMOUS")
    with github_authentication("anonymous"):
        assert resolve_github_token(fallback="not-used") == ""
    assert os.environ.get("CODETURTLE_ANONYMOUS") == before


@pytest.mark.parametrize("operator", ["/", "//", "%"])
def test_removed_numeric_guard_is_statically_substantiated(operator):
    import difflib
    from core.rules.python_contracts import removed_zero_guard_candidates
    from core.runtime.verify_loop import verify_candidates
    from core.verification.diff_index import build_diff_index
    before = f"def arithmetic(numerator, denominator):\n    if denominator == 0:\n        return 0\n    return numerator {operator} denominator\n"
    after = f"def arithmetic(numerator, denominator):\n    return numerator {operator} denominator\n"
    diff = "diff --git a/app.py b/app.py\n" + "".join(difflib.unified_diff(before.splitlines(True), after.splitlines(True), fromfile="a/app.py", tofile="b/app.py"))
    index = build_diff_index(diff)
    candidates = removed_zero_guard_candidates(index, {"app.py": "b1"})
    assert len(candidates) == 1
    kept, dropped = verify_candidates(candidates, index=index)
    assert len(kept) == 1 and not dropped and kept[0].verify_status == "verified"
    # Independently execute the controlled code fixture: actual BASE/HEAD behavior.
    namespace = {}
    exec(before, namespace)
    assert namespace["arithmetic"](1, 0) == 0
    exec(after, namespace)
    with pytest.raises(ZeroDivisionError): namespace["arithmetic"](1, 0)


@pytest.mark.parametrize("after", [
    "def arithmetic(n, d):\n    if d == 0:\n        return 0\n    return n / d\n",
    "def arithmetic(n, d):\n    return n + d\n",
    "def arithmetic(n, d):\n    return external(n) / d\n",
    "@wrapped\ndef arithmetic(n, d):\n    return n / d\n",
])
def test_numeric_contract_rule_abstains_outside_exact_pattern(after):
    import difflib
    from core.rules.python_contracts import removed_zero_guard_candidates
    from core.verification.diff_index import build_diff_index
    before = "def arithmetic(n, d):\n    if d == 0:\n        return 0\n    return n / d\n"
    diff = "diff --git a/app.py b/app.py\n" + "".join(difflib.unified_diff(before.splitlines(True), after.splitlines(True), fromfile="a/app.py", tofile="b/app.py"))
    assert removed_zero_guard_candidates(build_diff_index(diff), {"app.py": "b1"}) == []
