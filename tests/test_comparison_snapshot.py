"""PR comparison identity remains distinct from the target branch's current tip."""
import hashlib
import json

from core.input.snapshot import GitSnapshotProvider
from tests.test_input_snapshot import git, repository


def test_merge_base_reads_do_not_include_later_target_branch_changes(repository):
    root, common = repository
    head = git(root, "rev-parse", "HEAD")
    git(root, "checkout", "--detach", common)
    (root / "app.py").write_text("limit = 99\n")
    git(root, "add", ".")
    git(root, "commit", "-m", "target branch advanced")
    target = git(root, "rev-parse", "HEAD")
    provider = GitSnapshotProvider(root)
    snapshot = provider.resolve(target, head, comparison="merge_base")
    assert snapshot.base_sha == target
    assert snapshot.comparison_base_sha == common
    assert provider.read(snapshot, "app.py", "base").content == b"limit = 1\n"
    assert provider.read(snapshot, "app.py", "head").content == b"limit = 2\n"
    assert "limit = 99" not in provider.diff(snapshot)
    assert provider.resolve(target, head).source_id != snapshot.source_id


def test_default_snapshot_identity_keeps_legacy_hash_shape(repository):
    root, base = repository
    snapshot = GitSnapshotProvider(root).resolve(base)
    previous = snapshot.model_dump(exclude={"comparison_base_sha"})
    expected = hashlib.sha256(json.dumps(previous, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    assert snapshot.comparison_base_sha is None
    assert snapshot.id == expected
