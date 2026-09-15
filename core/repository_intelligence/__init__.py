"""Repository Intelligence package."""

from core.repository_intelligence.service import (
    IndexResult,
    RepoStats,
    RepositoryIntelligenceService,
)

__all__ = [
    "IndexResult",
    "RepoStats",
    "RepositoryIntelligence",
    "RepositoryIntelligenceService",
]


def __getattr__(name: str):
    if name == "RepositoryIntelligence":
        from core.repository_intelligence.pipeline import RepositoryIntelligence

        return RepositoryIntelligence
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
