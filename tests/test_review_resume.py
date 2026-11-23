import json
from types import SimpleNamespace

from typer.testing import CliRunner

from cli.main import app
from core.agent.bundle_agent import AgentRunResult
from core.runtime.review_runtime import ReviewRuntime
from tests.test_gateway_http import ollama_server
from tests.test_input_snapshot import repository, git
from tests.test_source_finding_verifier import verification_case, candidate


def test_incremental_review_carries_unresolved_prior_findings(verification_case):
    provider, snapshot = verification_case()
    class Discovery:
        def run_result(self, bundle, tools):
            c = candidate(); c.bundle_id = bundle.id
            return AgentRunResult(status="VALID_CANDIDATES", candidates=[c])
    result = ReviewRuntime(agent=Discovery(), rule_engine=lambda *a,**k: []).run(SimpleNamespace(
        review_snapshot=snapshot,input_provider=provider,repo_dir=str(provider.root),
        pr_base_sha=snapshot.base_sha,pr_head_sha=snapshot.head_sha,
        files_changed=["app.py"],full_diff=provider.diff(snapshot)))
    previous = provider.root/"previous.json"; previous.write_text(json.dumps(result.to_dict()))
    (provider.root/"README.md").write_text("Documentation only")
    git(provider.root,"add","README.md"); git(provider.root,"commit","-m","docs")
    output = provider.root/"incremental.json"
    response = CliRunner().invoke(app,["review-local","--repo",str(provider.root),"--base",snapshot.head_sha,
        "--previous",str(previous),"--static-only","--json-output",str(output)])
    assert response.exit_code == 0, response.output
    data = json.loads(output.read_text())
    assert data["decision"] == "COMMENT" and not data["approval_eligible"]
    assert any(x["reason"] == "previous_finding_requires_revalidation" for x in data["unresolved"])
    next_base=git(provider.root,"rev-parse","HEAD")
    (provider.root/"README.md").write_text("Another documentation update")
    git(provider.root,"commit","-am","docs again")
    third=provider.root/"third.json"
    response=CliRunner().invoke(app,["review-local","--repo",str(provider.root),"--base",next_base,
        "--previous",str(output),"--static-only","--json-output",str(third)])
    assert response.exit_code==0,response.output
    assert any(x["reason"]=="previous_finding_requires_revalidation" for x in json.loads(third.read_text())["unresolved"])


def test_native_checkpoint_reuse_still_runs_independent_final_verification(verification_case, ollama_server):
    from tests.test_semantic_review import assessment
    provider,snapshot = verification_case()
    requests,state = ollama_server
    expected = {"kind":"return_value","property":"return","value":"0"}
    actual = {"kind":"raises","property":"return","value":"TypeError"}
    def respond(prompt):
        package=json.loads(prompt.split("\nPACKAGE\n",1)[1])
        if "units" in package:
            row=assessment(package["units"][0]["unit_id"],regression=True)
            row.update(contract="None input returns zero",behavioral_delta="None guard removed")
            row["hypothesis"]={"symbol":"size","trigger":"items is None","expected":expected,"suspected":actual}
            return json.dumps({"assessments":[row]})
        result={"conclusion":"violation_supported","reason":"None reaches len","missing_evidence":[]}
        for side,value,line in [("base",expected,3),("head",actual,2)]:
            span = next(x for x in package["source_spans"]
                        if x["side"] == side and x["start_line"] == x["end_line"] == line)
            result[side] = value | {"span_id": span["span_id"]}
        return json.dumps(result)
    state["respond"]=respond
    context=SimpleNamespace(review_snapshot=snapshot,input_provider=provider,repo_dir=str(provider.root),
        pr_base_sha=snapshot.base_sha,pr_head_sha=snapshot.head_sha,files_changed=["app.py"],
        full_diff=provider.diff(snapshot),checkpoint_dir=provider.root/"checkpoints")
    first=ReviewRuntime(rule_engine=lambda *a,**k: []).run(context)
    second=ReviewRuntime(rule_engine=lambda *a,**k: []).run(context)
    assert len(requests)==2
    assert second.agent_runs[0]["checkpoint_reused"] is True
    assert first.decision==second.decision=="REQUEST_CHANGES"
    assert second.finding_verifications[0].verification_method=="source_rule"
    assert second.provenance["budget"]["calls"]==0
