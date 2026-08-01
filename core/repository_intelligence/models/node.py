from __future__ import annotations
import hashlib
from typing import Optional
from pydantic import BaseModel, Field


class NodeID(BaseModel):
    """
    Deterministic, stable identifier for any graph node.
    Same logical entity always gets the same ID across re-indexes.
    """
    value: str

    @classmethod
    def from_parts(cls, repo: str, kind: str, qualified_name: str) -> "NodeID":
        raw = f"{repo}::{kind}::{qualified_name}".encode("utf-8")
        digest = hashlib.sha256(raw).hexdigest()[:32]
        return cls(value=f"{kind}:{digest}")

    def __str__(self) -> str:
        return self.value

    def __hash__(self) -> int:
        return hash(self.value)