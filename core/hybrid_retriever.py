import re
from typing import List, Dict, Any, Optional
from langchain_core.documents import Document
from qdrant_client.models import FieldCondition, Filter, MatchValue

from core.knowledge_base import KnowledgeBase
from core.repository_intelligence import RepositoryIntelligence
from core.repository_persistence import RepositoryPersistence
from core.evidence import Evidence, EvidencePackage


class HybridRetriever:
    def __init__(self, repo_name: str, kb: Optional[KnowledgeBase] = None):
        self.repo_name = repo_name
        self.kb = kb or KnowledgeBase(repo_name.replace("/", "_"))

    def retrieve(self, query: str, k: int = 8) -> List[Document]:
        print(f"[HybridRetriever] Querying collection: {self.repo_name.replace('/', '_')}")
        
        # Vector search
        vector_docs = self.kb.similarity_search(query, k=k)

        print(f"[HybridRetriever] Vector search returned {len(vector_docs)} documents")
        
        return vector_docs

    def _vector_search(self, query: str, k: int) -> List[Document]:
        """Semantic search using Qdrant."""
        return self.kb.similarity_search(query, k=k)

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
        """Placeholder for metadata search."""
        return []

    def _deduplicate(self, documents: List[Document]) -> List[Document]:
        """Remove duplicate documents by path."""
        seen = {}
        unique = []
        for doc in documents:
            path = doc.metadata.get("path")
            if path and path not in seen:
                seen[path] = True
                unique.append(doc)
        return unique