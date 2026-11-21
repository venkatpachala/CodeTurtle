"""Normal PR investigations cannot mix sealed diffs with mutable source."""
from types import SimpleNamespace
import hashlib

import pytest

from core.agent.bundle_agent import AgentRunResult
from core.analysis.risk_signals import analyze_risk_signals
from core.input.snapshot import GitSnapshotProvider, InputError
from core.input.tools import SnapshotBundleTools
from core.runtime.models import Bundle
from core.runtime.review_runtime import ReviewRuntime
from core.verification.diff_index import build_diff_index
from tests.test_input_snapshot import git, repository


def context(root, base):
    provider = GitSnapshotProvider(root)
    snapshot = provider.resolve(base, comparison="merge_base")
    diff = provider.diff(snapshot)
    return SimpleNamespace(repo_dir=str(root), files_changed=["app.py"], full_diff=diff,
        pr_base_sha=base, pr_head_sha=snapshot.head_sha, pr_input_provider=provider,
        pr_review_snapshot=snapshot, source_preparation={"status": "ready",
            "review_diff_sha256": hashlib.sha256(diff.encode()).hexdigest()})


def test_pr_routes_source_and_search_to_pinned_objects_before_any_agent_work(repository):
    root, base = repository
    ctx = context(root, base)
    seen = []
    class Inspector:
        def run_result(self, bundle, tools):
            seen.extend([tools.read_source("app.py"), tools.graph_callers("limit")])
            return AgentRunResult(status="VALID_EMPTY")
    (root / "app.py").write_text("mutable = 999\n")
    result = ReviewRuntime(agent=Inspector()).run(ctx)
    assert all(item["snapshot_id"] == ctx.pr_review_snapshot.id for item in seen)
    assert "limit = 2" in seen[0]["text"] and "mutable" not in seen[0]["text"]
    assert "limit = 2" in seen[1]["text"]
    assert result.provenance["investigation_source"] == "git_snapshot"
    ctx.pr_head_sha = "a" * 40
    with pytest.raises(InputError, match="runtime review identity"):
        ReviewRuntime(agent=Inspector()).run(ctx)
    assert len(seen) == 2  # Identity rejection precedes tool/model work.


def test_unavailable_pr_snapshot_never_falls_back_to_checkout(repository):
    root, base = repository
    ctx = context(root, base)
    ctx.pr_input_provider = ctx.pr_review_snapshot = None
    ctx.source_preparation = {"status": "unavailable"}
    seen = []
    class Inspector:
        def run_result(self, bundle, tools):
            seen.append(tools.read_source("app.py"))
            return AgentRunResult(status="VALID_EMPTY")
    result = ReviewRuntime(agent=Inspector()).run(ctx)
    assert seen[0]["error"] == "no_scoped_checkout"
    assert result.provenance["investigation_source"] == "unavailable"
    assert result.health.status == "partial"


def test_snapshot_source_window_uses_only_requested_files_change_units(repository):
    root, base = repository
    (root / "long.py").write_text("\n" * 300 + "changed = 42\n")
    git(root, "add", ".")
    git(root, "commit", "-m", "add later source")
    provider = GitSnapshotProvider(root)
    snapshot = provider.resolve(base)
    tools = SnapshotBundleTools(Bundle(id="B1", paths=["app.py", "long.py"],
        units=[{"path": "app.py", "start_line": 1}, {"path": "long.py", "start_line": 301}]),
        index=build_diff_index(provider.diff(snapshot)), provider=provider, snapshot=snapshot)
    assert "301: changed = 42" in tools.read_source("long.py")["text"]


def test_snapshot_risk_and_ruby_callee_context_survive_checkout_mutation(repository):
    root, base = repository
    model = root / "optimized_image.rb"
    model.write_text("class OptimizedImage\n  def self.downsize(a,b,dimensions,opts={})\n    gifsicle = '--resize-fit'\n  end\n  def self.downsize(a,b,c,d)\n  end\nend\n")
    (root / "caller.rb").write_text('OptimizedImage.downsize(a,b,"80%",allow_animation: true)\n')
    git(root, "add", ".")
    git(root, "commit", "-m", "Ruby source")
    provider = GitSnapshotProvider(root)
    snapshot = provider.resolve(base)
    index = build_diff_index(provider.diff(snapshot))
    model.write_text("unrelated mutable content\n")
    signals = analyze_risk_signals(repo_dir=None, files_changed=["optimized_image.rb", "caller.rb"], index=index,
        read_source=lambda p: provider.read(snapshot, p).content.decode(), repository_paths=provider.paths(snapshot))
    assert {"duplicate_definition", "cross_file_argument_contract"} <= {s.kind for s in signals}
    tools = SnapshotBundleTools(Bundle(id="B1", paths=["caller.rb"]), index=index, provider=provider, snapshot=snapshot)
    result = tools.callee_contract("OptimizedImage.downsize")
    assert result["revision_sha"] == snapshot.head_sha
    assert "--resize-fit" in result["text"] and "unrelated" not in result["text"]
    assert result["truncated"]  # It is an excerpt, not whole-file proof.
