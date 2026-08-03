"""Repository Intelligence package."""
from core.repository_intelligence.pipeline import RepositoryIntelligence
from core.repository_intelligence.service import (
    RepositoryIntelligenceService,
    IndexResult,
    RepoStats,
)
__all__ = ["RepositoryIntelligence"]

# from core.repository_intelligence.service import RepositoryIntelligenceService

# def add_repo(repo: str, force: bool = False, ...):
#     svc = RepositoryIntelligenceService(repo)
#     result = svc.ensure_indexed(force=force)  # or svc.index(force=True)
#     # print IndexResult with rich Panel