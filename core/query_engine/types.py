"""Stable domain types returned by the Query Engine (no Neo4j/Qdrant leakage)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, List, Optional


def normalize_path(path: str) -> str:
    return (path or "").replace("\\", "/").lstrip("./")


@dataclass
class SymbolHit:
    name: str
    type: str  # class | function | method | ...
    path: str
    line: Optional[int] = None
    docstring: Optional[str] = None
    qualified_name: Optional[str] = None
    decorators: List[str] = field(default_factory=list)

    def __post_init__(self):
        self.path = normalize_path(self.path)


@dataclass
class FileHit:
    path: str
    language: str = "unknown"
    line_count: int = 0
    symbol_count: int = 0
    imports: List[str] = field(default_factory=list)
    preview: str = ""

    def __post_init__(self):
        self.path = normalize_path(self.path)


@dataclass
class CallEdge:
    caller: str
    callee: str
    caller_path: Optional[str] = None
    callee_path: Optional[str] = None

    def __post_init__(self):
        if self.caller_path:
            self.caller_path = normalize_path(self.caller_path)
        if self.callee_path:
            self.callee_path = normalize_path(self.callee_path)


@dataclass
class DependencyEdge:
    source_path: str
    target_path: str
    kind: str = "IMPORTS"  # IMPORTS | reverse_IMPORTS

    def __post_init__(self):
        self.source_path = normalize_path(self.source_path)
        self.target_path = normalize_path(self.target_path)


@dataclass
class ImpactReport:
    seed_paths: List[str]
    affected_files: List[str] = field(default_factory=list)
    affected_symbols: List[str] = field(default_factory=list)
    depth: int = 1
    edges_considered: int = 0
    notes: List[str] = field(default_factory=list)


@dataclass
class RepositorySummary:
    repo_name: str
    total_files: int = 0
    total_symbols: int = 0
    languages: List[str] = field(default_factory=list)
    indexed_at: Optional[datetime] = None
    extra: dict = field(default_factory=dict)


@dataclass
class ArchitectureSummary:
    """Thin v1 — deterministic package/hub stats, not LLM prose."""
    repo_name: str
    top_level_packages: List[str] = field(default_factory=list)
    files_per_package: dict = field(default_factory=dict)
    import_hubs: List[str] = field(default_factory=list)  # most-imported paths
    notes: List[str] = field(default_factory=list)


# EvidencePackage: re-export if you already have one in core
# from core.evidence import EvidencePackage  # prefer existing
# For now a thin alias placeholder — wire to your real type in engine later.
@dataclass
class EvidenceItem:
    path: str
    content: str
    score: float = 0.0
    source: str = "unknown"  # vector | path | symbol | graph
    metadata: dict = field(default_factory=dict)

    def __post_init__(self):
        self.path = normalize_path(self.path)


@dataclass
class EvidencePackage:
    evidences: List[EvidenceItem] = field(default_factory=list)
    query: str = ""
    summary: str = ""

    @property
    def count(self) -> int:
        return len(self.evidences)