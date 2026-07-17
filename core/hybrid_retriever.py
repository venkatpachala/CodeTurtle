from typing import List, Optional
from langchain_core.documents import Document

from core.knowledge_base import KnowledgeBase
from core.reranker import Reranker
from core.repository_persistence import RepositoryPersistence
from core.context_builder import ContextBuilder
from core.evidence import EvidencePackage

class HybridRetriever:
    def __init__(self, repo_name: str, kb: Optional[KnowledgeBase] = None):
        self.repo_name = repo_name
        self.kb = kb or KnowledgeBase(repo_name.replace("/", "_"))
        self.reranker = Reranker()

    def retrieve(self, query: str, pr_understanding: dict = None, k: int = 8) -> EvidencePackage:
        print(f"[HybridRetriever] Querying collection: {self.repo_name.replace('/', '_')}")

        # Vector search
        vector_docs = self.kb.similarity_search(query, k=k * 2)

        # Symbol search
        symbol_docs = self._symbol_search(query, k=k // 2)

        all_docs = vector_docs + symbol_docs

        # Rerank
        ranked_docs = self.reranker.rerank(query, all_docs, top_k=k)

        print(f"[HybridRetriever] Retrieved {len(all_docs)} → reranked to {len(ranked_docs)} documents")

        # Build Evidence Package
        package = ContextBuilder.build(
            query=query,
            pr_understanding=pr_understanding or {},
            documents=ranked_docs
        )

        return package

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
                            page_content=f"Symbol: {symbol.name} ({symbol.type})\nFile: {key.split('::')[0]}",
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
        """Placeholder for future metadata filtering."""
        return []