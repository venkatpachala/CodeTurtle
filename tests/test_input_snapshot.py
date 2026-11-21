"""Actual Git object reads: revision drift, path escapes, symlinks, and budgets."""
from pathlib import Path
import subprocess

import pytest

from core.input.snapshot import GitSnapshotProvider, InputError


def git(root: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True,
                          text=True).stdout.strip()


@pytest.fixture
def repository(tmp_path):
    git(tmp_path, "init")
    git(tmp_path, "config", "user.name", "Snapshot test")
    git(tmp_path, "config", "user.email", "snapshot@example.invalid")
    (tmp_path / "app.py").write_text("limit = 1\n")
    git(tmp_path, "add", ".")
    git(tmp_path, "commit", "-m", "base")
    base = git(tmp_path, "rev-parse", "HEAD")
    (tmp_path / "app.py").write_text("limit = 2\n")
    git(tmp_path, "add", ".")
    git(tmp_path, "commit", "-m", "head")
    return tmp_path, base


def test_snapshot_reads_stay_pinned_after_worktree_and_head_change(repository):
    root, base = repository
    provider = GitSnapshotProvider(root)
    snapshot = provider.resolve(base)
    expected_diff = provider.diff(snapshot)
    (root / "app.py").write_text("limit = 999\n")
    git(root, "add", ".")
    git(root, "commit", "-m", "later")
    assert provider.read(snapshot, "app.py").content == b"limit = 2\n"
    assert provider.read(snapshot, "app.py", "base").content == b"limit = 1\n"
    assert provider.diff(snapshot) == expected_diff
    assert git(root, "rev-parse", "HEAD") != snapshot.head_sha


def test_identity_is_deterministic_and_configuration_sensitive(repository):
    root, base = repository
    provider = GitSnapshotProvider(root)
    assert provider.resolve(base).id == provider.resolve(base).id
    assert provider.resolve(base).id != provider.resolve(base, config={"mode": "deep"}).id
    assert provider.resolve(base).source_id == provider.resolve(base, config={"mode": "deep"}).source_id


@pytest.mark.parametrize("path", ["../secret", "/etc/passwd", "C:/secret", "a/../app.py", "./app.py", "a\\b", ":(glob)*"])
def test_rejects_nonliteral_and_escaping_paths(repository, path):
    root, base = repository
    provider = GitSnapshotProvider(root)
    with pytest.raises(InputError, match="repository-relative"):
        provider.read(provider.resolve(base), path)


def test_missing_files_and_oversized_reads_fail_explicitly(repository):
    root, base = repository
    provider = GitSnapshotProvider(root, max_source_bytes=2)
    snapshot = provider.resolve(base)
    with pytest.raises(InputError, match="absent"):
        provider.read(snapshot, "missing.py")
    with pytest.raises(InputError, match="byte budget"):
        provider.read(snapshot, "app.py")


def test_rejects_symlink_blobs_without_following_them(repository):
    root, base = repository
    # Write a symlink entry through the index; works without OS symlink privileges.
    blob = git(root, "rev-parse", "HEAD:app.py")
    git(root, "update-index", "--add", "--cacheinfo", f"120000,{blob},link.py")
    git(root, "commit", "-m", "link")
    provider = GitSnapshotProvider(root)
    with pytest.raises(InputError, match="regular"):
        provider.read(provider.resolve(base), "link.py")


def test_foreign_snapshot_and_tampered_diff_are_rejected(repository):
    root, base = repository
    provider = GitSnapshotProvider(root)
    snapshot = provider.resolve(base)
    with pytest.raises(InputError, match="another repository"):
        provider.read(snapshot.model_copy(update={"repository_identity": "elsewhere"}), "app.py")
    with pytest.raises(InputError, match="integrity"):
        provider.diff(snapshot.model_copy(update={"diff_sha256": "0" * 64}))
