"""Exercise the normal gateway/provider over real local HTTP, without a model.

The server implements the Ollama chat response used by the SDK. These are
transport-contract tests, not measurements of model reasoning.
"""
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

import pytest
from pydantic import BaseModel, ConfigDict

from config import settings
from core.gateway.gateway import AIGateway


@pytest.fixture
def ollama_server(monkeypatch):
    requests = []
    state = {"failures": 0}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            requests.append({"path": self.path, "body": request})
            failed = len(requests) <= state["failures"]
            if "respond" in state:
                state["content"] = state["respond"](request["messages"][-1]["content"])
            payload = {"error": "fixture service unavailable"} if failed else {
                "model": request["model"], "created_at": "2026-11-21T00:00:00Z",
                "message": {"role": "assistant", "content": state["contents"][len(requests)-1] if "contents" in state else state.get("content", "gateway-ok")},
                "done": True, "done_reason": state.get("done_reason", "stop"), "prompt_eval_count": 5, "eval_count": 2,
            }
            content = (json.dumps(payload) + "\n").encode()
            self.send_response(503 if failed else 200)
            self.send_header("Content-Type", "application/x-ndjson")
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setattr(settings, "ollama_base_url", f"http://127.0.0.1:{server.server_port}")
    monkeypatch.setattr(settings, "ollama_model", "gateway-fixture")
    monkeypatch.setattr(settings, "llm_backend", "ollama")
    try:
        yield requests, state
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


@pytest.mark.parametrize("attempt_budget", [0, 1])
def test_zero_or_one_attempt_budget_sends_one_actual_request(ollama_server, attempt_budget):
    requests, _ = ollama_server
    response = AIGateway().generate("transport probe", retries=attempt_budget, max_tokens=16, temperature=0)
    assert response.content == "gateway-ok"
    assert len(requests) == 1
    assert requests[0]["path"] == "/api/chat"
    assert requests[0]["body"]["options"]["num_predict"] == 16
    assert response.usage == {"prompt_tokens": 5, "completion_tokens": 2}
    assert response.telemetry.retries == 0


def test_zero_retry_failure_does_not_repeat_the_request(ollama_server):
    requests, state = ollama_server
    state["failures"] = 10
    with pytest.raises(RuntimeError, match="1 attempt"):
        AIGateway().generate("transport probe", retries=0)
    assert len(requests) == 1


def test_positive_legacy_budget_bounds_attempts_and_records_retry(ollama_server):
    requests, state = ollama_server
    state["failures"] = 1
    response = AIGateway().generate("transport probe", retries=2)
    assert len(requests) == 2
    assert response.telemetry.retries == 1


def test_negative_budget_is_rejected_without_network_request(ollama_server):
    requests, _ = ollama_server
    with pytest.raises(ValueError, match="nonnegative"):
        AIGateway().generate("transport probe", retries=-1)
    assert not requests


class StructuredReply(BaseModel):
    model_config = ConfigDict(extra="forbid")
    answer: str


def test_schema_and_context_reach_the_real_sdk_http_request(ollama_server):
    requests, state = ollama_server
    state["content"] = '{"answer":"ok"}'
    response = AIGateway().generate("JSON answer", response_schema=StructuredReply, retries=0)
    assert requests[0]["body"]["format"] == StructuredReply.model_json_schema()
    assert requests[0]["body"]["options"]["num_ctx"] == settings.ollama_context_tokens
    assert response.content == state["content"]  # Raw response remains available for validation/repair.
    assert response.telemetry.response_format == "json_schema"
    assert response.telemetry.finish_reason == "stop"
    assert response.telemetry.schema_sha256


def test_truncation_is_transport_success_but_explicitly_recorded(ollama_server):
    _, state = ollama_server
    state.update(content='{"answer":', done_reason="length")
    response = AIGateway().generate("JSON answer", response_schema=StructuredReply, max_tokens=8, retries=0)
    assert response.telemetry.success and response.telemetry.output_truncated
    assert response.telemetry.max_output_tokens == 8
    assert response.content == '{"answer":'


def test_parsed_structured_calls_keep_usage(ollama_server):
    _, state = ollama_server
    state["content"] = '{"answer":"ok"}'
    response = AIGateway().generate("JSON answer", structured_output=StructuredReply, retries=0)
    assert response.content.answer == "ok"
    assert response.usage["completion_tokens"] == 2


def test_explicit_legacy_agent_sends_proof_schema_through_normal_gateway(ollama_server):
    from core.agent.bundle_agent import BundleAgent
    from core.runtime.models import Bundle
    requests, state = ollama_server
    discovery = {"hypotheses": [{"file": "app.py", "symbol": "size", "category": "correctness",
        "observation": "guard changed", "hypothesis": "None may reach len", "required_evidence": ["source"]}]}
    proof = {"decisions": [{"hypothesis_id": "H-001", "status": "unresolved", "candidate": None,
        "reason": "Caller contract unavailable", "evidence_refs": [], "missing_evidence": ["caller contract"]}]}
    state["contents"] = [json.dumps(discovery), json.dumps(proof)]
    agent = BundleAgent(discovery_protocol="legacy")
    result = agent.run_result(Bundle(id="B-001", paths=["app.py"]))
    assert result.status == "VALID_EMPTY"
    assert len(requests) == 2
    assert requests[1]["body"]["format"]["properties"]["decisions"]
    assert agent.usage_records[1]["stage"] == "proof"
    assert result.proof_runs[0]["status"] == "completed"


def test_default_semantic_agent_uses_native_schema_and_pinned_sources(ollama_server, tmp_path):
    from core.agent.bundle_agent import BundleAgent
    from tests.test_semantic_review import assessment, pinned_tools, proof_for
    requests, state = ollama_server
    bundle, tools = pinned_tools(tmp_path)
    def respond(prompt):
        package = json.loads(prompt.split("\nPACKAGE\n", 1)[1])
        return json.dumps({"assessments": [assessment(regression=True)]}) if "units" in package else json.dumps(proof_for(prompt))
    state["respond"] = respond
    agent = BundleAgent()
    result = agent.run_result(bundle, tools)
    assert result.status == "VALID_CANDIDATES" and len(result.candidates) == 1
    assert result.discovery_protocol == "semantic-v1"
    assert len(requests) == 2 and len(agent.usage_records) == 2
    assert requests[0]["body"]["format"]["properties"]["assessments"]
    assert requests[1]["body"]["format"]["properties"]["conclusion"]
    assert agent.usage_records[0]["stage"] == "semantic_discovery"
    assert agent.usage_records[1]["stage"] == "semantic_proof"


def test_runtime_final_gate_requests_schema_and_validates_citations(ollama_server, tmp_path):
    from types import SimpleNamespace
    from core.input.snapshot import GitSnapshotProvider
    from core.runtime.review_runtime import ReviewRuntime
    from core.domain.finding_verification import FindingDecision
    from tests.test_input_snapshot import git
    from tests.test_source_finding_verifier import candidate, response_for, PROTECTED, BROKEN
    requests, state = ollama_server
    git(tmp_path, "init")
    git(tmp_path, "config", "user.name", "HTTP test")
    git(tmp_path, "config", "user.email", "http@example.invalid")
    (tmp_path / "app.py").write_text(PROTECTED)
    git(tmp_path, "add", ".")
    git(tmp_path, "commit", "-m", "base")
    base = git(tmp_path, "rev-parse", "HEAD")
    (tmp_path / "app.py").write_text(BROKEN)
    git(tmp_path, "commit", "-am", "head")
    provider = GitSnapshotProvider(tmp_path)
    snapshot = provider.resolve(base)
    state["respond"] = lambda prompt: json.dumps(response_for(prompt))
    fixed_agent = SimpleNamespace(run=lambda *a, **k: [candidate()])
    result = ReviewRuntime(agent=fixed_agent, rule_engine=lambda *a, **k: [], finding_source_rules=False).run(SimpleNamespace(
        repo_dir=str(tmp_path), pr_base_sha=base, pr_head_sha=snapshot.head_sha,
        files_changed=["app.py"], full_diff=provider.diff(snapshot)))
    assert len(requests) == 1
    assert requests[0]["body"]["format"] == FindingDecision.model_json_schema()
    assert result.finding_verifications[0].verdict == "supported"
    from core.runtime.models import ReviewResult
    assert ReviewResult.from_dict(result.to_dict()).to_dict() == result.to_dict()
    assert len(result.product_findings) == 1


def test_native_semantic_discovery_reaches_independent_rule_and_product(ollama_server, tmp_path):
    """Positive end-to-end control: rejecting everything cannot pass this test."""
    from types import SimpleNamespace
    from core.input.snapshot import GitSnapshotProvider
    from core.runtime.review_runtime import ReviewRuntime
    from tests.test_input_snapshot import git
    from tests.test_source_finding_verifier import PROTECTED, BROKEN
    from tests.test_semantic_review import assessment
    requests, state = ollama_server
    git(tmp_path, "init")
    git(tmp_path, "config", "user.name", "HTTP semantic test")
    git(tmp_path, "config", "user.email", "test@example.invalid")
    (tmp_path / "app.py").write_text(PROTECTED)
    git(tmp_path, "add", ".")
    git(tmp_path, "commit", "-m", "correct baseline")
    base = git(tmp_path, "rev-parse", "HEAD")
    (tmp_path / "app.py").write_text(BROKEN)
    git(tmp_path, "commit", "-am", "introduced regression")
    provider = GitSnapshotProvider(tmp_path)
    snapshot = provider.resolve(base)
    expected = {"kind": "return_value", "property": "return", "value": "0"}
    actual = {"kind": "raises", "property": "return", "value": "TypeError"}
    def respond(prompt):
        package = json.loads(prompt.split("\nPACKAGE\n", 1)[1])
        if "units" in package:
            rows = []
            for unit in package["units"]:
                row = assessment(unit["unit_id"], regression=True)
                row.update(behavioral_delta="Removed None guard", contract="None input returns zero")
                row["hypothesis"] = {"symbol": "size", "trigger": "items is None", "expected": expected, "suspected": actual}
                rows.append(row)
            return json.dumps({"assessments": rows})
        observed = {}
        for side, value, line in (("base", expected, 3), ("head", actual, 2)):
            span = next(e for e in package["source_spans"] if e["side"] == side and e["start_line"] == e["end_line"] == line)
            observed[side] = {**value, "span_id": span["span_id"]}
        return json.dumps({"conclusion": "violation_supported", "reason": "None reaches builtin len", **observed, "missing_evidence": []})
    state["respond"] = respond
    result = ReviewRuntime(rule_engine=lambda *a, **k: []).run(SimpleNamespace(
        review_snapshot=snapshot, input_provider=provider, repo_dir=str(tmp_path),
        pr_base_sha=base, pr_head_sha=snapshot.head_sha,
        files_changed=["app.py"], full_diff=provider.diff(snapshot)))
    assert len(requests) == 2
    assert result.decision == "REQUEST_CHANGES" and len(result.product_findings) == 1
    assert result.finding_verifications[0].verification_method == "source_rule"
    assert result.finding_verifications[0].verdict == "supported"
