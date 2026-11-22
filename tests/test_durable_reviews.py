import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from typer.testing import CliRunner

from cli.main import app
from core.review.checkpoints import BundleCheckpoints
from core.review.jobs import JobStore, LostLease
from core.runtime.models import Bundle, Candidate
from tests.test_input_snapshot import repository


def payload():
    return {"repo": "repo", "base_sha": "a"*40, "head_sha": "b"*40}


def test_concurrent_submit_and_claim_are_idempotent_and_exclusive(tmp_path):
    store = JobStore(tmp_path/"jobs.db")
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: store.submit(payload()), range(16)))
        claims = list(pool.map(lambda _: store.claim(), range(8)))
    assert len({job["id"] for job in results}) == 1
    assert sum(job is not None for job in claims) == 1
    with pytest.raises(ValueError, match="different"):
        store.submit({"different": True}, key=results[0]["key"])


def test_crashed_worker_lease_recovery_fences_stale_completion(tmp_path):
    now = [100.0]
    store = JobStore(tmp_path/"jobs.db", clock=lambda: now[0])
    submitted = store.submit(payload())
    first = store.claim(lease_seconds=10)
    now[0] = 111
    second = store.claim()
    assert second["id"] == submitted["id"] and second["attempt"] == 2
    with pytest.raises(LostLease): store.finish(first["id"], first["token"], report={"target":payload()})
    assert store.finish(second["id"], second["token"], report={"target":payload()})["state"] == "succeeded"
    assert "lease_expired" in [event["event"] for event in store.events(first["id"])]


def test_cancellation_is_terminal_even_when_worker_finishes_late(tmp_path):
    store = JobStore(tmp_path/"jobs.db")
    job = store.submit(payload())
    claimed = store.claim()
    store.cancel(job["id"])
    assert store.heartbeat(job["id"], claimed["token"]) is True
    assert store.finish(job["id"], claimed["token"], report={"target":payload()})["state"] == "cancelled"
    assert store.claim() is None
    store.retry(job["id"])
    assert store.claim()["attempt"] == 2


def test_wrong_target_never_commits_success(tmp_path):
    store = JobStore(tmp_path/"jobs.db")
    store.submit(payload())
    claimed = store.claim()
    with pytest.raises(ValueError, match="target"):
        store.finish(claimed["id"], claimed["token"], report={"target":{"head_sha":"c"*40}})
    assert store.get(claimed["id"])["state"] == "running"


def test_missing_finding_is_not_automatically_resolved(tmp_path):
    store = JobStore(tmp_path/"jobs.db")
    one = store.submit(payload()); claimed = store.claim()
    finding = {"file":"a.py","invariant":"reads stay bounded","violating_condition":"large input","expected":"bounded","actual":"unbounded"}
    store.finish(one["id"], claimed["token"], report={"target":payload(),"product_findings":[finding]})
    two = store.submit(payload()|{"head_sha":"c"*40}); claimed = store.claim()
    store.finish(two["id"], claimed["token"], report={"target":payload()|{"head_sha":"c"*40},"product_findings":[]})
    tracked = store.findings("repo")[0]
    assert tracked["state"] == "needs_recheck"
    with pytest.raises(ValueError): store.finding_state("repo", tracked["fingerprint"], "resolved", actor="", evidence="")
    store.finding_state("repo", tracked["fingerprint"], "resolved", actor="reviewer", evidence="pinned reproducer passed")
    assert store.findings("repo")[0]["state"] == "resolved"


def test_checkpoint_rejects_corruption_and_changed_input_identity(tmp_path):
    bundle = Bundle(id="B1", paths=["app.py"])
    checkpoints = BundleCheckpoints(tmp_path, {"snapshot":"one","reviewer":"v1"})
    checkpoints.save(bundle, [Candidate(bundle_id="B1", file="app.py")], {"status":"VALID_CANDIDATES"})
    assert checkpoints.load(bundle)[1]["checkpoint_reused"]
    assert BundleCheckpoints(tmp_path, {"snapshot":"two","reviewer":"v1"}).load(bundle) is None
    path = next(tmp_path.glob("*.json")); path.write_text("broken")
    assert checkpoints.load(bundle) is None


def test_queue_and_worker_execute_real_static_cli_and_preserve_artifact(repository):
    root, base = repository
    db = root/"jobs.db"
    runner = CliRunner()
    args = ["jobs","submit","--repo",str(root),"--base",base,"--static-only","--db",str(db)]
    response = runner.invoke(app, args)
    assert response.exit_code == 0, response.output
    job_id = json.loads(response.output)["id"]
    repeated = runner.invoke(app, args)
    assert json.loads(repeated.output)["id"] == job_id
    worked = runner.invoke(app, ["jobs","work","--db",str(db)])
    assert worked.exit_code == 0, worked.output
    job = JobStore(db).get(job_id)
    assert job["state"] == "succeeded", job
    data = json.loads(Path(job["artifact"]).read_text())
    assert data["provenance"]["analysis_mode"] == "static_only"
    assert data["provenance"]["budget"]["calls"] == 0


def test_worker_enforces_deadline_and_records_failure(repository):
    from core.review.checkpoints import reviewer_identity
    from core.review.worker import review_config, work_once
    from core.input.snapshot import GitSnapshotProvider
    root, base = repository
    provider = GitSnapshotProvider(root); snapshot = provider.resolve(base)
    store = JobStore(root/"deadline.db")
    job = store.submit({"repo":provider.identity,"base_sha":snapshot.base_sha,"head_sha":snapshot.head_sha,
                       "diff_sha256":snapshot.diff_sha256,"reviewer":reviewer_identity(),"review_config":review_config(),
                       "static_only":True,"bundle_max":4,"timeout_seconds":0.001})
    result = work_once(store, poll_seconds=0.005)
    assert result["id"] == job["id"] and result["state"] == "failed"
    assert result["error"] == "worker_deadline_exceeded"
