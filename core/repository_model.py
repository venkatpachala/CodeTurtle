from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from datetime import datetime


class FileModel(BaseModel):
    """Rich structured representation of a single file in the repository."""

    path: str
    language: str = "unknown"
    module: Optional[str] = None
    size_bytes: int = 0
    extension: str = ""

    # Code structure (will be enriched with AST later)
    classes: List[str] = Field(default_factory=list)
    functions: List[str] = Field(default_factory=list)
    imports: List[str] = Field(default_factory=list)
    exports: List[str] = Field(default_factory=list)

    # Relationships (for future Graph DB)
    dependencies: List[str] = Field(default_factory=list)   # files this file depends on
    dependents: List[str] = Field(default_factory=list)     # files that depend on this file

    # Semantic content
    summary: str = ""
    embedding: Optional[List[float]] = None

    # Metadata
    last_modified: Optional[datetime] = None
    extra: Dict[str, Any] = Field(default_factory=dict)


class RepositoryModel(BaseModel):
    """Top-level structured model representing an entire indexed repository."""

    repo_name: str
    total_files: int = 0
    languages: List[str] = Field(default_factory=list)
    indexed_at: datetime = Field(default_factory=datetime.now)
    files: List[FileModel] = Field(default_factory=list)

    # Future extensions
    # dependency_graph: Optional[Dict] = None
    # summary: Optional[str] = None