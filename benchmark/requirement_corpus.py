"""Load frozen input-only requirement fixtures; annotations are a separate file."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, model_validator

from core.input.snapshot import GitSnapshotProvider
from core.intent.service import ScopedRequirement


class FileVersions(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    base: str | None
    head: str | None


class RequirementCase(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    case_id: str = Field(pattern=r"^[a-z0-9-]{1,100}$")
    files: dict[str, FileVersions]
    requirements: tuple[ScopedRequirement, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_source_paths(self):
        for path in self.files:
            GitSnapshotProvider._path(path)
            if any(part.casefold().rstrip(" .") == ".git" for part in path.split("/")):
                raise ValueError("fixture cannot write Git control files")
        if len({item.id for item in self.requirements}) != len(self.requirements):
            raise ValueError("duplicate requirement ID")
        return self


def load_corpus(root: Path) -> tuple[dict, list[RequirementCase]]:
    manifest = json.loads((root / "manifest.json").read_text())
    if (manifest.get("split") != "development" or manifest.get("eligible_for_headline_metrics") is not False):
        raise ValueError("requirement corpus must be explicitly development-only")
    content = (root / "inputs.json").read_bytes()
    if hashlib.sha256(content).hexdigest() != manifest.get("inputs_sha256"):
        raise ValueError("frozen corpus input integrity mismatch")
    cases = [RequirementCase.model_validate(case) for case in json.loads(content)]
    if len(cases) != manifest.get("case_count") or len({case.case_id for case in cases}) != len(cases):
        raise ValueError("corpus count or unique identities mismatch")
    return manifest, cases
