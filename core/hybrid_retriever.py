from typing import List, Optional
from langchain_core.documents import Document

from core.knowledge_base import KnowledgeBase
from core.reranker import Reranker
from core.repository_persistence import RepositoryPersistence
from core.context_builder import ContextBuilder
from core.evidence import EvidencePackage
from core.query_builder import RetrievalQuery

try:
    from core.repository_intelligence.graph.queries import GraphQueries
except ImportError:
    GraphQueries = None


class HybridRetriever:
    def __init__(self, repo_name: str, kb: Optional[KnowledgeBase] = None):
        self.repo_name = repo_name
        self.kb = kb or KnowledgeBase(repo_name.replace("/", "_"))
        self.reranker = Reranker()
        self._graph = GraphQueries() if GraphQueries else None
        self._last_graph_expansion: List[str] = []

    def retrieve(
        self,
        query: str,
        pr_understanding: dict = None,
        files_changed: List[str] | None = None,
        k: int = 8,
    ) -> EvidencePackage:
        """Vector + symbol search, then IMPORTS graph expansion, then rerank."""
        print(f"[HybridRetriever] Querying collection: {self.repo_name.replace('/', '_')}")
        pr_understanding = pr_understanding or {}
        files_changed = files_changed or []

        # --- 1. Vector search ---
        vector_docs = self.kb.similarity_search(query, k=k * 2)

        # --- 2. Symbol search ---
        symbol_docs = self._symbol_search(query, k=k // 2)

        all_docs = list(vector_docs) + list(symbol_docs)

        # --- 3. Seed paths for graph expansion ---
        seed_paths = self._collect_seed_paths(
            docs=all_docs,
            pr_understanding=pr_understanding,
            files_changed=files_changed,
        )

        # --- 4. Phase 3: IMPORTS expansion ---
        graph_docs: List[Document] = []
        if self._graph and seed_paths:
            expanded = self._graph.expand_paths(seed_paths, limit_per=8)
            self._last_graph_expansion = expanded
            print(
                f"[HybridRetriever] Graph expansion: "
                f"{len(seed_paths)} seeds → {len(expanded)} paths"
            )
            graph_docs = self._docs_for_paths(expanded, exclude={d.metadata.get("path") for d in all_docs if d.metadata})
            all_docs.extend(graph_docs)
        else:
            self._last_graph_expansion = []

        # --- 5. Rerank ---
        ranked_docs = self.reranker.rerank(query, all_docs, top_k=k)

        print(
            f"[HybridRetriever] Retrieved {len(vector_docs)} vector + "
            f"{len(symbol_docs)} symbol + {len(graph_docs)} graph → "
            f"reranked to {len(ranked_docs)} documents"
        )

        # --- 6. Evidence package + dependency context ---
        package = ContextBuilder.build(
            query=query,
            pr_understanding=pr_understanding,
            documents=ranked_docs,
        )

        # Attach human-readable IMPORTS context for agents (if package allows)
        dep_context = self._format_dependency_context(seed_paths)
        if dep_context:
            if hasattr(package, "dependency_context"):
                package.dependency_context = dep_context
            # Also fold into a common text field if your package has it
            if hasattr(package, "extra_context"):
                package.extra_context = (getattr(package, "extra_context", "") or "") + "\n" + dep_context

        return package

    def retrieve_multi(
        self,
        queries: List[RetrievalQuery],
        k_per_query: int = 6,
        max_total: int = 12,
        pr_understanding: dict = None,
        files_changed: List[str] | None = None,
    ) -> EvidencePackage:
        """Multi-query retrieval with weighting, dedup, and one graph expansion pass."""
        print(f"[HybridRetriever] Multi-query retrieval with {len(queries)} queries")
        pr_understanding = pr_understanding or {}
        files_changed = files_changed or []

        all_docs = []
        for q in queries:
            package = self.retrieve(
                q.text,
                pr_understanding=pr_understanding,
                files_changed=files_changed,
                k=k_per_query,
            )
            docs = package.evidences if hasattr(package, "evidences") else []
            for doc in docs:
                doc.source_query = q.text
                doc.query_category = q.category
                doc.query_weight = q.weight
                all_docs.append(doc)

        unique = {}
        for doc in all_docs:
            file_path = getattr(doc, "path", None) or (doc.metadata or {}).get("path")
            if not file_path:
                continue
            score = getattr(doc, "score", 0) * getattr(doc, "query_weight", 1.0)
            if file_path not in unique or score > unique[file_path][1]:
                unique[file_path] = (doc, score)

        final_docs = [
            doc for doc, _ in sorted(unique.values(), key=lambda x: x[1], reverse=True)
        ][:max_total]

        print(
            f"[HybridRetriever] Retrieved {len(all_docs)} → "
            f"deduplicated to {len(final_docs)} documents"
        )

        package = ContextBuilder.build(
            query=" | ".join(q.text for q in queries),
            pr_understanding=pr_understanding,
            documents=final_docs,
        )
        return package

    def _collect_seed_paths(
        self,
        docs: List[Document],
        pr_understanding: dict,
        files_changed: List[str],
    ) -> List[str]:
        seeds: List[str] = []

        for p in files_changed:
            if p:
                seeds.append(p.replace("\\", "/"))

        for key in ("affected_files", "changed_files", "files_changed", "high_risk_files"):
            for p in pr_understanding.get(key) or []:
                if isinstance(p, str) and p:
                    seeds.append(p.replace("\\", "/"))

        for d in docs:
            meta = d.metadata or {}
            p = meta.get("path")
            if p:
                seeds.append(str(p).replace("\\", "/"))

        # dedupe, preserve order
        return list(dict.fromkeys(seeds))

    def _docs_for_paths(self, paths: List[str], exclude: set | None = None) -> List[Document]:
        """
        Pull KB chunks for graph-expanded paths so agents get real code,
        not only path names.
        """
        exclude = exclude or set()
        out: List[Document] = []
        seen = set()

        for path in paths:
            if path in exclude or path in seen:
                continue
            seen.add(path)
            try:
                # Prefer metadata filter if your KB supports it; else query by path string
                hits = self.kb.similarity_search(path, k=2)
                for h in hits:
                    meta = h.metadata or {}
                    if meta.get("path") == path or path in (h.page_content or ""):
                        meta = {**meta, "path": meta.get("path") or path, "retrieval_type": "graph_imports"}
                        h.metadata = meta
                        out.append(h)
                        break
                else:
                    # Lightweight placeholder evidence if no chunk matched
                    out.append(
                        Document(
                            page_content=f"[Graph IMPORTS] Related file: {path}",
                            metadata={"path": path, "retrieval_type": "graph_imports"},
                        )
                    )
            except Exception:
                out.append(
                    Document(
                        page_content=f"[Graph IMPORTS] Related file: {path}",
                        metadata={"path": path, "retrieval_type": "graph_imports"},
                    )
                )
            if len(out) >= 16:
                break
        return out

    def _format_dependency_context(self, seed_paths: List[str]) -> str:
        if not self._graph or not seed_paths:
            return ""
        lines = ["### Repository dependency context (IMPORTS)"]
        for p in seed_paths[:12]:
            deps = self._graph.direct_imports(p, limit=8)
            imps = self._graph.importers(p, limit=8)
            if not deps and not imps:
                continue
            lines.append(f"\n**{p}**")
            if deps:
                lines.append(f"  imports: {', '.join(deps)}")
            if imps:
                lines.append(f"  imported by: {', '.join(imps)}")
        return "\n".join(lines) if len(lines) > 1 else ""

    def _symbol_search(self, query: str, k: int) -> List[Document]:
        """Fast lookup using symbol index."""
        try:
            persistence = RepositoryPersistence(self.repo_name)
            repository_model = persistence.load_repository_model()

            if not repository_model or not repository_model.symbol_index:
                return []

            results = []
            for key, symbol in repository_model.symbol_index.items():
                if query.lower() in key.lower() or query.lower() in symbol.name.lower():
                    results.append(
                        Document(
                            page_content=(
                                f"Symbol: {symbol.name} ({symbol.type})\n"
                                f"File: {key.split('::')[0]}"
                            ),
                            metadata={
                                "path": key.split("::")[0],
                                "symbol": symbol.name,
                                "type": symbol.type,
                                "retrieval_type": "symbol",
                            },
                        )
                    )
                    if len(results) >= k:
                        break
            return results
        except Exception:
            return []

    def _metadata_search(self, query: str, k: int) -> List[Document]:
        return []