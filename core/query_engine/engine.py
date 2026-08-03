"""Repository Query Engine — single public read API over Model + Neo4j + Qdrant."""

from __future__ import annotations

from typing import List, Optional

from core.query_engine.errors import GraphUnavailableError, RepoNotIndexedError
from core.query_engine.routers.graph_router import GraphRouter
from core.query_engine.routers.model_router import ModelRouter
from core.query_engine.routers.vector_router import VectorRouter
from core.query_engine.types import (
    CallEdge,
    DependencyEdge,
    EvidencePackage,
    FileHit,
    ImpactReport,
    RepositorySummary,
    SymbolHit,
    normalize_path,
)


class RepositoryQueryEngine:
    def __init__(
        self,
        repo_name: str,
        repository_model=None,
        graph_store=None,
        kb=None,
    ):
        self.repo_name = repo_name
        self._model = ModelRouter(repo_name, repository_model=repository_model)
        self._graph = GraphRouter(repo_name, graph_store=graph_store)
        self._vector = VectorRouter(repo_name, kb=kb)

    # ── Structure ──────────────────────────────────────────────────

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

    # ── Graph ──────────────────────────────────────────────────────

    def find_dependencies(
        self,
        path: str,
        *,
        direction: str = "out",
        limit: int = 100,
    ) -> List[DependencyEdge]:
        if not self._graph.available:
            raise GraphUnavailableError("Neo4j not connected")
        return self._graph.find_dependencies(path, direction=direction, limit=limit)

    def find_callers(
        self,
        symbol: str,
        *,
        path: Optional[str] = None,
        limit: int = 50,
    ) -> List[CallEdge]:
        if not self._graph.available:
            raise GraphUnavailableError("Neo4j not connected")
        return self._graph.find_callers(symbol, path=path, limit=limit)

    def find_callees(
        self,
        symbol: str,
        *,
        path: Optional[str] = None,
        limit: int = 50,
    ) -> List[CallEdge]:
        if not self._graph.available:
            raise GraphUnavailableError("Neo4j not connected")
        return self._graph.find_callees(symbol, path=path, limit=limit)

    # ── Retrieval (Step 4) ─────────────────────────────────────────

    def retrieve_context(
        self,
        query: str,
        *,
        files_changed: Optional[List[str]] = None,
        symbols: Optional[List[str]] = None,
        k: int = 8,
        use_graph: bool = True,
        pr_understanding: Optional[dict] = None,
        fail_if_empty: bool = False,
    ) -> EvidencePackage:
        return self._vector.retrieve_context(
            query,
            files_changed=files_changed,
            symbols=symbols,
            k=k,
            use_graph=use_graph,
            pr_understanding=pr_understanding,
            fail_if_empty=fail_if_empty,
        )

    # ── Impact (thin graph-only Step 5 preview) ────────────────────

    def impact_analysis(
        self,
        paths: List[str],
        *,
        depth: int = 2,
    ) -> ImpactReport:
        paths = [normalize_path(p) for p in paths if p]
        affected_files: set[str] = set(paths)
        edges_considered = 0
        notes: List[str] = []

        if not self._graph.available:
            notes.append("Neo4j unavailable; impact limited to seed paths")
            return ImpactReport(
                seed_paths=paths,
                affected_files=sorted(affected_files),
                depth=depth,
                edges_considered=0,
                notes=notes,
            )

        frontier = list(paths)
        for _ in range(max(1, depth)):
            next_frontier: List[str] = []
            for p in frontier:
                try:
                    for e in self._graph.find_dependencies(p, direction="in", limit=50):
                        edges_considered += 1
                        if e.source_path not in affected_files:
                            affected_files.add(e.source_path)
                            next_frontier.append(e.source_path)
                    for e in self._graph.find_dependencies(p, direction="out", limit=50):
                        edges_considered += 1
                        if e.target_path not in affected_files:
                            affected_files.add(e.target_path)
                            next_frontier.append(e.target_path)
                except Exception as ex:
                    notes.append(f"deps failed for {p}: {ex}")
            frontier = next_frontier
            if not frontier:
                break

        return ImpactReport(
            seed_paths=paths,
            affected_files=sorted(affected_files),
            depth=depth,
            edges_considered=edges_considered,
            notes=notes,
        )

    def architecture_summary(self):
        raise NotImplementedError("Architecture summary later")

    # ── Health ─────────────────────────────────────────────────────

    def stats(self) -> dict:
        summary = self.repository_summary()
        return {
            "repo_name": summary.repo_name,
            "total_files": summary.total_files,
            "total_symbols": summary.total_symbols,
            "languages": summary.languages,
            "indexed_at": str(summary.indexed_at) if summary.indexed_at else None,
            "graph": self._graph.available,
            "vector": self._vector.available,
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
            "neo4j": self._graph.available,
            "qdrant": self._vector.available,
        }