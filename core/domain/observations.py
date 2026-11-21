"""Tool-produced source observations and exact, independently checked citations."""
from __future__ import annotations

import hashlib
import json
from typing import Annotated, Literal

from pydantic import Field, StringConstraints, model_validator

from core.domain.review_contracts import ContentHash, DomainRecord, NonBlank, RevisionSHA, RevisionSide


class SourceObservation(DomainRecord):
    id: NonBlank
    snapshot_id: ContentHash
    revision_sha: RevisionSHA
    revision_side: RevisionSide
    path: NonBlank
    status: Literal["success", "truncated", "absent", "error"]
    start_line: int = Field(default=1, ge=1)
    end_line: int = Field(default=0, ge=0)
    text: str = Field(default="", max_length=24_000)
    file_sha256: ContentHash | None = None
    excerpt_sha256: ContentHash
    detail: str = ""

    @model_validator(mode="after")
    def check_excerpt(self) -> SourceObservation:
        if hashlib.sha256(self.text.encode()).hexdigest() != self.excerpt_sha256:
            raise ValueError("observation excerpt integrity mismatch")
        if self.status in {"success", "truncated"}:
            if self.file_sha256 is None or self.end_line != self.start_line + len(self.text.splitlines()) - 1:
                raise ValueError("source observation requires a file digest and exact line range")
        elif self.text or self.file_sha256 is not None:
            raise ValueError("unavailable observations cannot contain source evidence")
        return self


class SourceCitation(DomainRecord):
    observation_id: NonBlank
    start_line: int = Field(ge=1)
    end_line: int = Field(ge=1)
    quote: Annotated[str, StringConstraints(min_length=1, max_length=8000)]

    def validate_against(self, observations: dict[str, SourceObservation]) -> SourceObservation:
        observation = observations.get(self.observation_id)
        if observation is None:
            raise ValueError("unknown source observation")
        if observation.status not in {"success", "truncated"}:
            raise ValueError("unavailable observation cannot support a citation")
        if not observation.start_line <= self.start_line <= self.end_line <= observation.end_line:
            raise ValueError("citation lies outside observed line range")
        lines = observation.text.splitlines()
        quoted = "\n".join(lines[self.start_line - observation.start_line:self.end_line - observation.start_line + 1])
        if not self.quote.strip() or self.quote != quoted:
            raise ValueError("citation quote does not match observed source")
        return observation


def observation_id(snapshot_id: str, side: str, path: str, text: str, status: str) -> str:
    identity = json.dumps([snapshot_id, side, path, text, status], separators=(",", ":"))
    return "OBS-" + hashlib.sha256(identity.encode()).hexdigest()[:24]
