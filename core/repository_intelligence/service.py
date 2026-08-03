"""Repository Intelligence Service — write/ops API (index, refresh, stats)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class IndexResult:
    repo_name: str
    success: bool
    files_indexed: int = 0
    chunks: int = 0
    symbols: int = 0
    graph_imports: int = 0
    message: str = ""
    errors: list[str] = field(default_factory=list)


@dataclass
class RepoStats:
    repo_name: str
    model_files: int = 0
    model_symbols: int = 0
    languages: list[str] = field(default_factory=list)
    indexed_at: Optional[str] = None
    neo4j_ok: bool = False
    model_ok: bool = False
    qdrant_ok: bool = False
    ready_for_review: bool = False


class RepositoryIntelligenceService:
    """
    Ops API for repository intelligence.

    - index / refresh / ensure_indexed  → mutate stores
    - health / stats                     → inspect readiness

    For queries (symbols, deps, evidence) use RepositoryQueryEngine.
    """

    def __init__(self, repo_name: str):
        self.repo_name = repo_name

    # ── Readiness ──────────────────────────────────────────────────

    def health(self) -> dict:
        from core.query_engine import RepositoryQueryEngine

        h = RepositoryQueryEngine(self.repo_name).health()
        ready = bool(h.get("model") and h.get("neo4j") and h.get("qdrant"))
        return {**h, "ready_for_review": ready}

    def stats(self) -> RepoStats:
        from core.query_engine import RepositoryQueryEngine

        engine = RepositoryQueryEngine(self.repo_name)
        try:
            s = engine.stats()
            h = engine.health()
            ready = bool(h.get("model") and h.get("neo4j") and h.get("qdrant"))
            return RepoStats(
                repo_name=self.repo_name,
                model_files=int(s.get("total_files") or 0),
                model_symbols=int(s.get("total_symbols") or 0),
                languages=list(s.get("languages") or []),
                indexed_at=s.get("indexed_at"),
                neo4j_ok=bool(h.get("neo4j")),
                model_ok=bool(h.get("model")),
                qdrant_ok=bool(h.get("qdrant")),
                ready_for_review=ready,
            )
        except Exception:
            return RepoStats(repo_name=self.repo_name)

    # ── Write ──────────────────────────────────────────────────────

    def ensure_indexed(self, *, force: bool = False, repo_path: str | None = None) -> IndexResult:
        if not force:
            st = self.stats()
            if st.ready_for_review and st.model_files > 0:
                return IndexResult(
                    repo_name=self.repo_name,
                    success=True,
                    files_indexed=st.model_files,
                    symbols=st.model_symbols,
                    message="already indexed",
                )
        return self.index(force=True, repo_path=repo_path)

    def refresh(self) -> IndexResult:
        """Incremental if available; otherwise full index."""
        try:
            ri = self._make_intelligence()
            if hasattr(ri, "refresh"):
                return self._normalize(ri.refresh())
        except Exception as e:
            return IndexResult(
                repo_name=self.repo_name,
                success=False,
                message="refresh failed",
                errors=[str(e)],
            )
        return self.index(force=True)

    # ── Internals ──────────────────────────────────────────────────

    def index(self, *, force: bool = True, repo_path: str | None = None) -> IndexResult:
        errors: list[str] = []
        try:
            ri = self._make_intelligence(repo_path=repo_path)
            out = self._call_index(ri, force=force)
            return self._normalize(out, ri=ri)
        except Exception as e:
            errors.append(str(e))
            return IndexResult(
                repo_name=self.repo_name,
                success=False,
                message="index failed",
                errors=errors,
            )


    def _make_intelligence(self, repo_path: str | None = None):
        from core.repository_intelligence import RepositoryIntelligence
        from pathlib import Path

        if repo_path is None:
            repo_path = str(Path("repos") / self.repo_name.replace("/", "_"))

        return RepositoryIntelligence(
            repo_path=repo_path,
            repo_name=self.repo_name,
        )


    def _call_index(self, ri, *, force: bool):
        if hasattr(ri, "index_repository"):
            try:
                return ri.index_repository(force=force)
            except TypeError:
                return ri.index_repository()
        for name in ("index", "run"):
            fn = getattr(ri, name, None)
            if fn is None:
                continue
            try:
                return fn(force=force)
            except TypeError:
                return fn()
        raise RuntimeError(
            "RepositoryIntelligence has no index_repository/index/run"
        )


    def _normalize(self, out, ri=None) -> IndexResult:
        if isinstance(out, IndexResult):
            return out
        if isinstance(out, dict):
            return IndexResult(
                repo_name=self.repo_name,
                success=bool(out.get("success", True)),
                files_indexed=int(
                    out.get("files_indexed")
                    or out.get("total_files")
                    or out.get("files")
                    or 0
                ),
                chunks=int(out.get("chunks") or out.get("total_chunks") or 0),
                symbols=int(out.get("symbols") or out.get("total_symbols") or 0),
                graph_imports=int(out.get("graph_imports") or 0),
                message=str(out.get("message") or "ok"),
                errors=list(out.get("errors") or []),
            )

        # Prefer live model after index
        files, symbols = 0, 0
        if ri is not None and getattr(ri, "repository_model", None) is not None:
            model = ri.repository_model
            files = int(getattr(model, "total_files", 0) or 0)
            symbols = len(getattr(model, "symbol_index", {}) or {})
            if not symbols and getattr(model, "files", None):
                symbols = sum(len(getattr(f, "symbols", []) or []) for f in model.files)

        if files == 0:
            st = self.stats()
            files, symbols = st.model_files, st.model_symbols

        return IndexResult(
            repo_name=self.repo_name,
            success=files > 0,
            files_indexed=files,
            symbols=symbols,
            message="ok",
        )