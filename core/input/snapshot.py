"""Sealed committed inputs backed by Git objects, independent of checkout state."""
from __future__ import annotations

import hashlib
import json
import subprocess
import tempfile
from pathlib import Path, PurePosixPath
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict

from core.domain.review_contracts import ContentHash, RevisionSHA

RevisionSide = Literal["base", "head"]


class InputError(RuntimeError):
    """Input cannot be resolved, read safely, or kept within its budget."""


class SourceNotFound(InputError):
    """The path is absent from this exact tree, including added/deleted files."""


class ReviewSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    repository_identity: str
    base_sha: RevisionSHA
    head_sha: RevisionSHA
    diff_sha256: ContentHash
    config_sha256: ContentHash
    schema_version: Literal["1.0"] = "1.0"

    @property
    def id(self) -> str:
        encoded = json.dumps(self.model_dump(), sort_keys=True, separators=(",", ":")).encode()
        return hashlib.sha256(encoded).hexdigest()

    def revision(self, side: RevisionSide) -> str:
        if side not in {"base", "head"}:
            raise InputError("revision side must be base or head")
        return self.base_sha if side == "base" else self.head_sha


class SourceRead(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    snapshot_id: ContentHash
    revision_sha: RevisionSHA
    side: RevisionSide
    path: str
    content: bytes
    content_sha256: ContentHash


class ReviewInputProvider(Protocol):
    def resolve(self, base: str, head: str = "HEAD", *, config: dict | None = None) -> ReviewSnapshot: ...
    def diff(self, snapshot: ReviewSnapshot) -> str: ...
    def read(self, snapshot: ReviewSnapshot, path: str, side: RevisionSide = "head") -> SourceRead: ...


class GitSnapshotProvider:
    """Read exact committed trees without checking out or importing PR code.

    This adapter intentionally does not capture staged/unstaged/untracked files.
    Git subprocess output is spooled to disk and bounded before loading in memory.
    """

    def __init__(self, root: str | Path, *, max_source_bytes: int = 1_000_000,
                 max_diff_bytes: int = 5_000_000, timeout_seconds: float = 15):
        self.root = Path(root).resolve()
        self.max_source_bytes = max_source_bytes
        self.max_diff_bytes = max_diff_bytes
        self.timeout_seconds = timeout_seconds
        if min(max_source_bytes, max_diff_bytes, timeout_seconds) <= 0:
            raise ValueError("input limits must be positive")
        self.identity = self._git("rev-parse", "--show-toplevel", limit=16_384).decode().strip()

    def _git(self, *args: str, limit: int) -> bytes:
        command = ["git", "--no-optional-locks", "-C", str(self.root), *args]
        try:
            with tempfile.TemporaryFile() as output, tempfile.TemporaryFile() as errors:
                result = subprocess.run(command, stdout=output, stderr=errors,
                                        timeout=self.timeout_seconds, check=False)
                if result.returncode:
                    raise InputError(f"git {args[0]} failed (exit {result.returncode})")
                if output.tell() > limit:
                    raise InputError(f"git {args[0]} exceeded input byte budget")
                output.seek(0)
                return output.read(limit)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise InputError(f"git {args[0]} unavailable or timed out") from exc

    def _assert_repository(self, snapshot: ReviewSnapshot) -> None:
        if snapshot.repository_identity != self.identity:
            raise InputError("snapshot belongs to another repository")

    def _commit(self, ref: str) -> str:
        return self._git("rev-parse", "--verify", "--end-of-options", f"{ref}^{{commit}}",
                         limit=256).decode().strip()

    def _diff(self, base: str, head: str) -> bytes:
        return self._git("diff", "--no-ext-diff", "--no-textconv", "--no-color", "--binary",
                         "--find-renames", base, head, "--", limit=self.max_diff_bytes)

    def resolve(self, base: str, head: str = "HEAD", *, config: dict | None = None) -> ReviewSnapshot:
        base_sha, head_sha = self._commit(base), self._commit(head)
        config_bytes = json.dumps(config or {}, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
        return ReviewSnapshot(
            repository_identity=self.identity, base_sha=base_sha, head_sha=head_sha,
            diff_sha256=hashlib.sha256(self._diff(base_sha, head_sha)).hexdigest(),
            config_sha256=hashlib.sha256(config_bytes).hexdigest(),
        )

    def diff(self, snapshot: ReviewSnapshot) -> str:
        self._assert_repository(snapshot)
        content = self._diff(snapshot.base_sha, snapshot.head_sha)
        if hashlib.sha256(content).hexdigest() != snapshot.diff_sha256:
            raise InputError("sealed diff integrity mismatch")
        return content.decode("utf-8", errors="replace")

    @staticmethod
    def _path(path: str) -> str:
        if (not path or "\\" in path or ":" in path or "\x00" in path
                or path.startswith("/") or any(part in {"", ".", ".."} for part in path.split("/"))):
            raise InputError("source path must be a normalized repository-relative path")
        return PurePosixPath(path).as_posix()

    def read(self, snapshot: ReviewSnapshot, path: str, side: RevisionSide = "head") -> SourceRead:
        self._assert_repository(snapshot)
        path = self._path(path)
        revision = snapshot.revision(side)
        entry = self._git("ls-tree", "-z", revision, "--", f":(literal){path}", limit=16_384)
        if not entry:
            raise SourceNotFound("source is absent from the specified revision")
        metadata, _, stored_path = entry.rstrip(b"\x00").partition(b"\t")
        parts = metadata.split()
        if len(parts) != 3 or parts[0] not in {b"100644", b"100755"} or stored_path.decode() != path:
            raise InputError("only regular committed source files can be read")
        blob_id = parts[2].decode()
        size = int(self._git("cat-file", "-s", blob_id, limit=256))
        if size > self.max_source_bytes:
            raise InputError("source exceeded input byte budget")
        content = self._git("cat-file", "blob", blob_id, limit=self.max_source_bytes)
        return SourceRead(snapshot_id=snapshot.id, revision_sha=revision, side=side,
                          path=path, content=content, content_sha256=hashlib.sha256(content).hexdigest())

    def paths(self, snapshot: ReviewSnapshot, side: RevisionSide = "head") -> tuple[str, ...]:
        self._assert_repository(snapshot)
        data = self._git("ls-tree", "-r", "--name-only", "-z", snapshot.revision(side),
                         limit=self.max_diff_bytes)
        return tuple(path.decode("utf-8") for path in data.split(b"\x00") if path)
