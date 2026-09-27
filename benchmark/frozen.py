"""Immutable PR input manifests, separate from gold labels."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
from pydantic import BaseModel, ConfigDict, Field
from core.review.artifacts import write_json_atomic


class FrozenCase(BaseModel):
    model_config = ConfigDict(extra="forbid")
    case_id: str = Field(pattern=r"^[A-Za-z0-9_.-]{1,120}$")
    repo: str
    number: int = Field(gt=0)
    base_sha: str = Field(pattern=r"^[a-fA-F0-9]{40}$")
    head_sha: str = Field(pattern=r"^[a-fA-F0-9]{40}$")
    diff_file: str
    diff_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    lineage_id: str
    split: str = Field(pattern=r"^(development|validation|test)$")


def verify_case(case: FrozenCase, root: Path) -> str:
    path = (root / case.diff_file).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ValueError("frozen input escapes dataset root")
    contents = path.read_bytes()
    if hashlib.sha256(contents).hexdigest() != case.diff_sha256:
        raise ValueError("frozen diff integrity failed")
    return contents.decode("utf-8")


def validate_partitions(cases: list[FrozenCase]) -> None:
    identities: set[tuple[str, int]] = set()
    lineages: dict[str, str] = {}
    for case in cases:
        identity = (case.repo.lower(), case.number)
        if identity in identities:
            raise ValueError("duplicate PR across frozen partitions")
        identities.add(identity)
        previous = lineages.setdefault(case.lineage_id, case.split)
        if previous != case.split:
            raise ValueError("related patch lineage crosses partitions")


def seal_predictions(path: Path, predictions: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lease = path.with_name(path.name + ".seal-lock")
    fd = os.open(lease, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    try:
        if path.exists():
            raise FileExistsError("sealed predictions cannot be overwritten")
        write_json_atomic(path, predictions)
    finally:
        os.close(fd)
        lease.unlink()
