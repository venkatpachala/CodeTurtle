"""Real shallow Git histories, bounded failures, and native pipeline integration."""
import hashlib
import subprocess
from types import SimpleNamespace

import pytest

from cli.commands.review import ReviewPipeline, PipelineContext
from core.input.preparation import prepare_pr_snapshot
from core.input.snapshot import GitSnapshotProvider, InputError
from core.runtime.review_runtime import ReviewRuntime
from tests.test_input_snapshot import git, repository


def test_shallow_divergent_history_is_fetched_without_changing_checkout(repository):
    root, common = repository
    git(root, "checkout", "-b", "proposal")
    for number in range(4):
        (root / "app.py").write_text(f"limit = {number + 3}\n")
        git(root, "commit", "-am", f"proposal {number}")
    head = git(root, "rev-parse", "HEAD")
    git(root, "checkout", "-b", "target", common)
    for number in range(3):
        (root / "app.py").write_text(f"limit = {number + 99}\n")
        git(root, "commit", "-am", f"target {number}")
    base = git(root, "rev-parse", "HEAD")
    clone = root / "shallow"
    git(root, "clone", "--depth", "1", "--branch", "proposal", root.as_uri(), str(clone))
    (clone / "app.py").write_text("uncommitted = True\n")
    with pytest.raises(InputError):
        GitSnapshotProvider(clone).resolve(base, head, comparison="merge_base")
    provider, snapshot, report = prepare_pr_snapshot(clone, base, head, "api-diff", depths=(1, 2, 8))
    assert report["attempted_fetch_depths"] == [1, 2, 8]
    assert snapshot.base_sha == base and snapshot.revision("base") == common
    assert provider.read(snapshot, "app.py", "base").content == b"limit = 1\n"
    assert provider.read(snapshot, "app.py").content == b"limit = 6\n"
    assert git(clone, "rev-parse", "HEAD") == head
    assert (clone / "app.py").read_text() == "uncommitted = True\n"


def test_available_objects_need_no_network(repository):
    root, base = repository
    head = git(root, "rev-parse", "HEAD")
    def forbidden(*args, **kwargs):
        raise AssertionError("unnecessary network request")
    _, _, report = prepare_pr_snapshot(root, base, head, "diff", run=forbidden)
    assert report["status"] == "ready" and report["attempted_fetch_depths"] == []


def test_unavailable_history_stops_at_three_attempts_and_hides_remote_errors(repository):
    root, _ = repository
    calls = []
    def timeout(argv, **kwargs):
        calls.append((argv, kwargs))
        raise subprocess.TimeoutExpired("credential-containing-command", kwargs["timeout"])
    with pytest.raises(InputError, match="bounded history") as error:
        prepare_pr_snapshot(root, "0" * 40, git(root, "rev-parse", "HEAD"), "diff", run=timeout)
    assert len(calls) == 3 and "credential" not in str(error.value)
    assert all(0 < kwargs["timeout"] <= 90 for _, kwargs in calls)
    assert not any("--unshallow" in argv for argv, _ in calls)


@pytest.mark.parametrize("revision", ["HEAD", "--upload-pack=bad", "abc123"])
def test_preparation_only_accepts_pinned_complete_hashes(repository, revision):
    root, base = repository
    with pytest.raises(InputError, match="complete commit"):
        prepare_pr_snapshot(root, base, revision, "diff")


def test_pipeline_prepares_source_and_runtime_reuses_snapshot(repository, monkeypatch):
    root, base = repository
    provider = GitSnapshotProvider(root)
    snapshot = provider.resolve(base)
    pipeline = ReviewPipeline()
    pipeline.context = PipelineContext(repo_dir=str(root), pr_base_sha=base,
        pr_head_sha=snapshot.head_sha, full_diff=provider.diff(snapshot), files_changed=["app.py"])
    pipeline._prepare_source_snapshot()
    assert pipeline.context.source_preparation["status"] == "ready"
    monkeypatch.setattr(GitSnapshotProvider, "resolve", lambda *a, **k: pytest.fail("late source resolution"))
    pipeline.context.analysis_mode = "static_only"
    result = ReviewRuntime(rule_engine=lambda *args, **kwargs: []).run(pipeline.context)
    assert result.provenance["verification_snapshot_id"] == pipeline.context.pr_review_snapshot.id
    assert result.provenance["source_preparation"]["review_diff_sha256"] == hashlib.sha256(pipeline.context.full_diff.encode()).hexdigest()
    pipeline.context.pr_head_sha = "a" * 40
    with pytest.raises(InputError, match="runtime review identity"):
        ReviewRuntime(rule_engine=lambda *a, **k: []).run(pipeline.context)


def test_pipeline_keeps_unavailable_source_explicit(monkeypatch):
    def unavailable(*a, **k):
        raise InputError("bounded input failure")
    monkeypatch.setattr("core.input.preparation.prepare_pr_snapshot", unavailable)
    pipeline = ReviewPipeline()
    pipeline._prepare_source_snapshot()
    assert pipeline.context.pr_review_snapshot is None
    assert pipeline.context.source_preparation == {"status": "unavailable", "reason": "bounded input failure"}
