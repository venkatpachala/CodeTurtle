from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from datetime import datetime


class FileModel(BaseModel):
    """Rich structured representation of a single file in the repository."""

    path: str
    language: str = "unknown"
    extension: str = ""
    size_bytes: int = 0

    # Semantic preview (not full summary)
    preview: str = ""

    # Code structure
    classes: List[str] = Field(default_factory=list)
    functions: List[str] = Field(default_factory=list)   # Module-level functions
    methods: List[str] = Field(default_factory=list)     # Class methods
    decorators: List[str] = Field(default_factory=list)
    docstrings: Dict[str, str] = Field(default_factory=dict)  # key = name, value = docstring

    # Imports
    imports: List[str] = Field(default_factory=list)

    # Relationships (for future Graph DB)
    dependencies: List[str] = Field(default_factory=list)
    dependents: List[str] = Field(default_factory=list)

    # Metadata
    line_count: int = 0
    last_modified: Optional[datetime] = None
    extra: Dict[str, Any] = Field(default_factory=dict)


class RepositoryModel(BaseModel):
    """Top-level structured model representing an entire indexed repository."""

    repo_name: str
    total_files: int = 0
    languages: List[str] = Field(default_factory=list)
    indexed_at: datetime = Field(default_factory=datetime.now)
    files: List[FileModel] = Field(default_factory=list)