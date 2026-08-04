"""Read-only vector / hybrid retrieval behind the Query Engine."""

from __future__ import annotations

from typing import Any, List, Optional

from core.query_engine.errors import VectorUnavailableError
from core.query_engine.types import EvidenceItem, EvidencePackage, normalize_path


class VectorRouter:
    def __init__(self, repo_name: str, kb=None):
        """
        kb: optional shared KnowledgeBase (preferred — one client per process).
        """
        self.repo_name = repo_name
        self.collection_name = repo_name.replace("/", "_")
        self._kb = kb
        self._available = False
        self._error = ""
        self._ensure_kb()

    @property
    def available(self) -> bool:
        return self._available

    @property
    def kb(self):
        return self._kb

    def _ensure_kb(self) -> None:
        if self._kb is not None:
            self._available = True
            return
        try:
            from core.knowledge_base import KnowledgeBase

            self._kb = KnowledgeBase(collection_name=self.collection_name)
            self._available = True
        except Exception as e:
            self._error = str(e)
            self._available = False

    def retrieve_context(
        self,
        query: str,
        *,
        files_changed: Optional[List[str]] = None,
        symbols: Optional[List[str]] = None,
        prefer_paths: Optional[List[str]] = None,
        prefer_symbols: Optional[List[str]] = None,
        full_diff: Optional[str] = None,
        k: int = 8,
        use_graph: bool = True,
        pr_understanding: Optional[dict] = None,
        fail_if_empty: bool = False,
    ) -> EvidencePackage:
        if not self._available or self._kb is None:
            raise VectorUnavailableError(self._error or "KnowledgeBase not available")

        query = (query or "").strip()
        files_changed = [normalize_path(p) for p in (files_changed or []) if p]
        prefer_paths = [normalize_path(p) for p in (prefer_paths or []) if p]
        symbols = list(symbols or [])
        prefer_symbols = list(prefer_symbols or [])

        # Prefer HybridRetriever when present
        package = None
        try:
            package = self._via_hybrid(
                query,
                files_changed=files_changed,
                symbols=symbols,
                prefer_paths=prefer_paths,
                prefer_symbols=prefer_symbols,
                full_diff=full_diff,
                k=k,
                use_graph=use_graph,
                pr_understanding=pr_understanding or {},
            )
        except Exception as hybrid_err:
            # Fallback: pure vector + path
            try:
                package = self._via_kb_only(
                    query,
                    files_changed=prefer_paths or files_changed,
                    k=k,
                )
            except Exception as kb_err:
                raise VectorUnavailableError(
                    f"hybrid: {hybrid_err}; kb: {kb_err}"
                )

        if fail_if_empty and (package is None or package.count == 0):
            raise VectorUnavailableError(
                f"No evidence for query in collection '{self.collection_name}'. "
                f"Re-index with: python -m cli.main add-repo {self.repo_name}"
            )

        return package or EvidencePackage(query=query, evidences=[])

    def _via_hybrid(
        self,
        query: str,
        *,
        files_changed: List[str],
        symbols: List[str],
        prefer_paths: Optional[List[str]] = None,
        prefer_symbols: Optional[List[str]] = None,
        full_diff: Optional[str] = None,
        k: int,
        use_graph: bool,
        pr_understanding: dict,
    ) -> EvidencePackage:
        from core.hybrid_retriever import HybridRetriever

        # Inject shared KB — do not let HybridRetriever open a second client
        try:
            retriever = HybridRetriever(self.repo_name, kb=self._kb)
        except TypeError:
            retriever = HybridRetriever(self.repo_name)
            if hasattr(retriever, "kb") and self._kb is not None:
                retriever.kb = self._kb

        target_paths = prefer_paths or files_changed
        target_symbols = prefer_symbols or symbols
        diff_text = full_diff or (pr_understanding or {}).get("full_diff") or ""

        try:
            result = retriever.retrieve(
                query=query,
                pr_understanding=pr_understanding,
                k=k,
                files_changed=files_changed,
                prefer_paths=target_paths,
                prefer_symbols=target_symbols,
                full_diff=diff_text,
            )
        except TypeError:
            try:
                result = retriever.retrieve(
                    query=query,
                    pr_understanding=pr_understanding,
                    k=k,
                    files_changed=files_changed,
                )
            except TypeError:
                result = retriever.retrieve(query, k=k)

        package = self._normalize_to_package(result, query=query, k=k)

        # Floor: hybrid often reranks to 1 — pad with path/vector hits
        if package.count < k and target_paths:
            extra = self._via_kb_only(query, files_changed=target_paths, k=k)
            seen = {(e.path, e.content[:120]) for e in package.evidences}
            for e in extra.evidences:
                key = (e.path, e.content[:120])
                if key not in seen:
                    package.evidences.append(e)
                    seen.add(key)
                if package.count >= k:
                    break
            package.evidences = package.evidences[:k]

        elif package.count < k:
            # No target paths — still try pure vector pad
            extra = self._via_kb_only(query, files_changed=[], k=k)
            seen = {(e.path, e.content[:120]) for e in package.evidences}
            for e in extra.evidences:
                key = (e.path, e.content[:120])
                if key not in seen:
                    package.evidences.append(e)
                    seen.add(key)
                if package.count >= k:
                    break
            package.evidences = package.evidences[:k]

        return package

    def _via_kb_only(
        self,
        query: str,
        *,
        files_changed: List[str],
        k: int,
    ) -> EvidencePackage:
        items: List[EvidenceItem] = []
        seen = set()

        # Exact path chunks first
        for path in files_changed:
            docs = []
            if hasattr(self._kb, "get_by_path"):
                try:
                    docs = self._kb.get_by_path(path, k=max(k, 10))
                except TypeError:
                    docs = self._kb.get_by_path(path)
            for doc in docs or []:
                item = self._doc_to_item(doc, source="path")
                key = (item.path, item.content[:200])
                if key not in seen:
                    seen.add(key)
                    items.append(item)

        # Vector search
        docs = []
        if hasattr(self._kb, "similarity_search"):
            docs = self._kb.similarity_search(query, k=k)
        for doc in docs or []:
            item = self._doc_to_item(doc, source="vector")
            key = (item.path, item.content[:200])
            if key not in seen:
                seen.add(key)
                items.append(item)

        # Prefer changed files in ordering
        if files_changed:
            changed = set(files_changed)
            items.sort(key=lambda x: (0 if x.path in changed else 1, -x.score))

        return EvidencePackage(query=query, evidences=items[:k])

    def _normalize_to_package(self, result: Any, *, query: str, k: int) -> EvidencePackage:
        """Accept EvidencePackage, list[Document], or object with .evidences."""
        if result is None:
            return EvidencePackage(query=query, evidences=[])

        # Already our type or duck-typed package
        if isinstance(result, EvidencePackage):
            result.query = result.query or query
            return result

        if hasattr(result, "evidences"):
            raw = list(result.evidences or [])
            items = []
            for e in raw:
                if isinstance(e, EvidenceItem):
                    items.append(e)
                elif hasattr(e, "page_content"):
                    items.append(self._doc_to_item(e, source="hybrid"))
                elif isinstance(e, dict):
                    items.append(
                        EvidenceItem(
                            path=normalize_path(
                                e.get("path") or e.get("metadata", {}).get("path", "")
                            ),
                            content=e.get("content") or e.get("page_content") or "",
                            score=float(e.get("score") or 0.0),
                            source=e.get("source") or "hybrid",
                            metadata=e.get("metadata") or {},
                        )
                    )
                else:
                    # object with path/content attributes
                    items.append(
                        EvidenceItem(
                            path=normalize_path(getattr(e, "path", "") or ""),
                            content=getattr(e, "content", None)
                            or getattr(e, "page_content", "")
                            or str(e),
                            score=float(getattr(e, "score", 0.0) or 0.0),
                            source=getattr(e, "source", "hybrid") or "hybrid",
                            metadata=getattr(e, "metadata", None) or {},
                        )
                    )
            return EvidencePackage(query=query, evidences=items[: max(k, len(items))])

        # list of LangChain Documents
        if isinstance(result, list):
            items = [self._doc_to_item(d, source="hybrid") for d in result]
            return EvidencePackage(query=query, evidences=items[:k])

        return EvidencePackage(query=query, evidences=[])

    def _doc_to_item(self, doc: Any, *, source: str) -> EvidenceItem:
        if hasattr(doc, "page_content"):
            meta = getattr(doc, "metadata", None) or {}
            if not isinstance(meta, dict):
                meta = {}
            path = normalize_path(str(meta.get("path") or meta.get("file") or ""))
            score = float(meta.get("score") or meta.get("relevance") or 0.0)
            return EvidenceItem(
                path=path,
                content=doc.page_content or "",
                score=score,
                source=source,
                metadata=meta,
            )
        if isinstance(doc, dict):
            meta = doc.get("metadata") or {}
            return EvidenceItem(
                path=normalize_path(str(doc.get("path") or meta.get("path") or "")),
                content=doc.get("page_content") or doc.get("content") or "",
                score=float(doc.get("score") or 0.0),
                source=source,
                metadata=meta if isinstance(meta, dict) else {},
            )
        return EvidenceItem(path="", content=str(doc), source=source)