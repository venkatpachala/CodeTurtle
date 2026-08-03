"""Read-only access to RepositoryModel / symbol_index."""

from __future__ import annotations

from typing import List, Optional

from core.query_engine.errors import FileNotFoundError, RepoNotIndexedError
from core.query_engine.types import (
    FileHit,
    RepositorySummary,
    SymbolHit,
    normalize_path,
)


class ModelRouter:
    def __init__(self, repo_name: str, repository_model=None):
        """
        repository_model: optional pre-loaded model (tests).
        Otherwise loads via RepositoryPersistence.
        """
        self.repo_name = repo_name
        if repository_model is not None:
            self.model = repository_model
        else:
            from core.repository_persistence import RepositoryPersistence

            persistence = RepositoryPersistence(repo_name)
            self.model = persistence.load_repository_model()
            if self.model is None:
                raise RepoNotIndexedError(repo_name)

    def find_file(self, path: str) -> Optional[FileHit]:
        path = normalize_path(path)
        for fm in self.model.files or []:
            if normalize_path(getattr(fm, "path", "")) == path:
                symbols = getattr(fm, "symbols", None) or []
                return FileHit(
                    path=path,
                    language=getattr(fm, "language", "unknown") or "unknown",
                    line_count=getattr(fm, "line_count", 0) or 0,
                    symbol_count=len(symbols),
                    imports=list(getattr(fm, "imports", None) or []),
                    preview=getattr(fm, "preview", "") or "",
                )
        return None

    def list_symbols(self, path: str) -> List[SymbolHit]:
        path = normalize_path(path)
        fm = None
        for f in self.model.files or []:
            if normalize_path(getattr(f, "path", "")) == path:
                fm = f
                break
        if fm is None:
            raise FileNotFoundError(path)

        hits: List[SymbolHit] = []
        for sym in getattr(fm, "symbols", None) or []:
            name = getattr(sym, "name", None) or ""
            if not name:
                continue
            hits.append(
                SymbolHit(
                    name=name,
                    type=getattr(sym, "type", "unknown") or "unknown",
                    path=path,
                    line=getattr(sym, "line", None),
                    docstring=getattr(sym, "docstring", None),
                    qualified_name=f"{path}::{name}",
                    decorators=list(getattr(sym, "decorators", None) or []),
                )
            )
        return hits

    def find_symbol(
        self,
        name: str,
        *,
        path: Optional[str] = None,
        limit: int = 50,
    ) -> List[SymbolHit]:
        """Search symbol_index and/or file symbols by exact name (case-sensitive)."""
        name = (name or "").strip()
        if not name:
            return []

        path_filter = normalize_path(path) if path else None
        hits: List[SymbolHit] = []

        # 1) Prefer symbol_index if present
        symbol_index = getattr(self.model, "symbol_index", None) or {}
        if isinstance(symbol_index, dict) and symbol_index:
            for key, sym in symbol_index.items():
                sym_name = getattr(sym, "name", None) or str(key).split(".")[-1]
                if sym_name != name and key != name and not str(key).endswith(f".{name}"):
                    # also allow key == name
                    if sym_name != name and key != name:
                        continue
                # path often encoded in key like path::name or module.Class.method
                sym_path = getattr(sym, "path", None)
                if sym_path is None and isinstance(key, str) and "::" in key:
                    sym_path = key.split("::", 1)[0]
                if sym_path is None and isinstance(key, str) and "/" in key:
                    # best-effort
                    sym_path = "/".join(key.replace("\\", "/").split("/")[:-1]) or ""
                sym_path = normalize_path(sym_path or "")
                if path_filter and sym_path and sym_path != path_filter:
                    continue
                hits.append(
                    SymbolHit(
                        name=getattr(sym, "name", None) or name,
                        type=getattr(sym, "type", "unknown") or "unknown",
                        path=sym_path,
                        line=getattr(sym, "line", None),
                        docstring=getattr(sym, "docstring", None),
                        qualified_name=str(key) if key else name,
                        decorators=list(getattr(sym, "decorators", None) or []),
                    )
                )
                if len(hits) >= limit:
                    return hits

        # 2) Fallback: scan files
        if not hits:
            for fm in self.model.files or []:
                fpath = normalize_path(getattr(fm, "path", ""))
                if path_filter and fpath != path_filter:
                    continue
                for sym in getattr(fm, "symbols", None) or []:
                    if getattr(sym, "name", None) == name:
                        hits.append(
                            SymbolHit(
                                name=name,
                                type=getattr(sym, "type", "unknown") or "unknown",
                                path=fpath,
                                line=getattr(sym, "line", None),
                                docstring=getattr(sym, "docstring", None),
                                qualified_name=f"{fpath}::{name}",
                                decorators=list(getattr(sym, "decorators", None) or []),
                            )
                        )
                        if len(hits) >= limit:
                            return hits

        return hits[:limit]

    def repository_summary(self) -> RepositorySummary:
        files = self.model.files or []
        languages = list(getattr(self.model, "languages", None) or [])
        if not languages:
            languages = sorted(
                {
                    getattr(f, "language", None)
                    for f in files
                    if getattr(f, "language", None)
                }
            )
        symbol_index = getattr(self.model, "symbol_index", None) or {}
        total_symbols = len(symbol_index) if symbol_index else sum(
            len(getattr(f, "symbols", None) or []) for f in files
        )
        return RepositorySummary(
            repo_name=getattr(self.model, "repo_name", None) or self.repo_name,
            total_files=getattr(self.model, "total_files", None) or len(files),
            total_symbols=total_symbols,
            languages=languages,
            indexed_at=getattr(self.model, "indexed_at", None),
        )