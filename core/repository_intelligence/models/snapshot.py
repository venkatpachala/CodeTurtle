from __future__ import annotations
from datetime import datetime
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field
from .parsed import ParsedFile


class RepositorySnapshot(BaseModel):
    """
    Stage 1 output — pure discovery, no deep semantics.
    """
    repo_name: str                          # owner/repo
    local_path: str
    commit_sha: Optional[str] = None
    branch: Optional[str] = None
    languages: List[str] = Field(default_factory=list)
    files: List[ParsedFile] = Field(default_factory=list)
    ignored_paths: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=datetime.utcnow)

    @property
    def total_files(self) -> int:
        return len(self.files)