"""Sealed input traverses actual bundle tools and the CLI."""
import json
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from cli.main import app
from core.agent.bundle_agent import AgentRunResult
from core.input.snapshot import GitSnapshotProvider, InputError
from core.input.tools import SnapshotBundleTools
from core.runtime.models import Bundle
from core.runtime.review_runtime import ReviewRuntime
from core.verification.diff_index import build_diff_index
from tests.test_input_snapshot import git, repository


def test_snapshot_tools_read_committed_content_and_record_provenance(repository):
    root, base = repository
    provider = GitSnapshotProvider(root)
    snapshot = provider.resolve(base)
    (root / "app.py").write_text("limit = 999\n")
    tools = SnapshotBundleTools(Bundle(id="B1", paths=["app.py"]),
                                index=build_diff_index(provider.diff(snapshot)),
                                provider=provider, snapshot=snapshot)
    source = tools.read_source("app.py")
    assert "limit = 2" in source["text"]
    assert "999" not in source["text"]
    assert source["revision_sha"] == snapshot.head_sha
    assert source["snapshot_id"] == snapshot.id
    assert tools.graph_callers("limit")["matches"][0]["text"] == "limit = 2"
    assert tools.read_source("secret.py")["status"] == "denied"


def test_runtime_refuses_inconsistent_snapshot_context(repository):
    root, base = repository
    provider = GitSnapshotProvider(root)
    snapshot = provider.resolve(base)
    context = SimpleNamespace(review_snapshot=snapshot, input_provider=provider,
                              full_diff="tampered", pr_head_sha=snapshot.head_sha,
                              pr_base_sha=snapshot.base_sha)
    with pytest.raises(InputError, match="sealed snapshot"):
        ReviewRuntime(llm=lambda _: "[]").run(context)


def test_runtime_routes_tools_through_snapshot_adapter(repository):
    root, base = repository
    provider = GitSnapshotProvider(root)
    snapshot = provider.resolve(base)
    observations = []
    class Inspector:
        def run_result(self, bundle, tools):
            observations.append(tools.read_source("app.py"))
            return AgentRunResult(status="VALID_EMPTY")
    (root / "app.py").write_text("mutable = True\n")
    result = ReviewRuntime(agent=Inspector()).run(SimpleNamespace(
        review_snapshot=snapshot, input_provider=provider, files_changed=["app.py"],
        full_diff=provider.diff(snapshot), pr_head_sha=snapshot.head_sha, pr_base_sha=snapshot.base_sha,
    ))
    assert observations[0]["source"] == "git_snapshot"
    assert "mutable" not in observations[0]["text"]
    assert result.provenance["snapshot_id"] == snapshot.id


def test_local_cli_is_read_only_and_honest_about_static_coverage(repository):
    root, base = repository
    before = git(root, "rev-parse", "HEAD")
    output = root / "result.json"
    response = CliRunner().invoke(app, ["review-local", "--repo", str(root), "--base", base,
                                       "--static-only", "--json-output", str(output)])
    assert response.exit_code == 0, response.output
    data = json.loads(output.read_text())
    assert data["provenance"]["analysis_mode"] == "static_only"
    assert data["inspection"]["inspected"] == 0
    assert data["decision"] == "COMMENT"
    assert data["target"]["head_sha"] == before
    assert git(root, "rev-parse", "HEAD") == before
