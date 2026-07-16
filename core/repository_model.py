from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from datetime import datetime


class Symbol(BaseModel):
    """Represents a code symbol (class, function, method)."""
    name: str
    type: str  # "class", "function", "method"
    line: Optional[int] = None
    docstring: Optional[str] = None
    decorators: List[str] = Field(default_factory=list)


class FileModel(BaseModel):
    """Rich structured representation of a single file."""

    path: str
    language: str = "unknown"
    extension: str = ""
    size_bytes: int = 0
    preview: str = ""

    # Unified symbols
    symbols: List[Symbol] = Field(default_factory=list)

    # Imports
    imports: List[str] = Field(default_factory=list)

    # Relationships
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

    # Symbol Index (fully qualified name → Symbol)
    symbol_index: Dict[str, Symbol] = Field(default_factory=dict)

    # Future
    # architecture_summary: Optional[str] = None