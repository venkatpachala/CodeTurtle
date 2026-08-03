"""Repository Query Engine — single public read API over Model + Neo4j + Qdrant."""

from __future__ import annotations

from typing import List, Optional

from core.query_engine.errors import RepoNotIndexedError
from core.query_engine.routers.model_router import ModelRouter
from core.query_engine.types import (
    FileHit,
    RepositorySummary,
    SymbolHit,
)


class RepositoryQueryEngine:
    """
    Public façade for repository knowledge.

    Phase 7 Step 1–2: structure queries via RepositoryModel.
    Graph + vector routers land in later steps.
    """

    def __init__(self, repo_name: str, repository_model=None):
        self.repo_name = repo_name
        self._model = ModelRouter(repo_name, repository_model=repository_model)
        # Placeholders for later steps
        self._graph = None
        self._vector = None

    # ── Structure (Model) ──────────────────────────────────────────

    def find_file(self, path: str) -> Optional[FileHit]:
        return self._model.find_file(path)

    def list_symbols(self, path: str) -> List[SymbolHit]:
        return self._model.list_symbols(path)

    def find_symbol(
        self,
        name: str,
        *,
        path: Optional[str] = None,
        limit: int = 50,
    ) -> List[SymbolHit]:
        return self._model.find_symbol(name, path=path, limit=limit)

    def repository_summary(self) -> RepositorySummary:
        return self._model.repository_summary()

    # ── Graph (Step 3) ─────────────────────────────────────────────

    def find_dependencies(self, path: str, *, direction: str = "out"):
        raise NotImplementedError("Graph router not wired yet (Phase 7 Step 3)")

    def find_callers(self, symbol: str, *, path: Optional[str] = None, limit: int = 50):
        raise NotImplementedError("Graph router not wired yet (Phase 7 Step 3)")

    def find_callees(self, symbol: str, *, path: Optional[str] = None, limit: int = 50):
        raise NotImplementedError("Graph router not wired yet (Phase 7 Step 3)")

    # ── Retrieval (Step 4) ─────────────────────────────────────────

    def retrieve_context(self, query: str, **kwargs):
        raise NotImplementedError("Vector/hybrid router not wired yet (Phase 7 Step 4)")

    def impact_analysis(self, paths: List[str], *, depth: int = 2):
        raise NotImplementedError("Impact analysis not wired yet (Phase 7 Step 5)")

    def architecture_summary(self):
        raise NotImplementedError("Architecture summary not wired yet (Phase 7 Step 6)")

    # ── Health ─────────────────────────────────────────────────────

    def stats(self) -> dict:
        summary = self.repository_summary()
        return {
            "repo_name": summary.repo_name,
            "total_files": summary.total_files,
            "total_symbols": summary.total_symbols,
            "languages": summary.languages,
            "indexed_at": str(summary.indexed_at) if summary.indexed_at else None,
            "graph": self._graph is not None,
            "vector": self._vector is not None,
        }

    def health(self) -> dict:
        try:
            s = self.repository_summary()
            model_ok = s.total_files > 0
        except RepoNotIndexedError:
            model_ok = False
        return {
            "repo_name": self.repo_name,
            "model": model_ok,
            "neo4j": False,   # until Step 3
            "qdrant": False,  # until Step 4
        }