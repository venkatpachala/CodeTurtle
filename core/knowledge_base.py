from langchain_qdrant import QdrantVectorStore
from langchain_ollama import OllamaEmbeddings
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams, Filter, FieldCondition, MatchValue
from langchain_core.documents import Document
from typing import List, Optional, Dict, Any


class KnowledgeBase:
    def __init__(self, collection_name: str):
        self.collection_name = collection_name
        self.embeddings = OllamaEmbeddings(model="nomic-embed-text")
        self.client = QdrantClient(
            host="localhost",
            port=6333,
        )

        self._ensure_collection_exists()

        self.vectorstore = QdrantVectorStore(
            client=self.client,
            collection_name=collection_name,
            embedding=self.embeddings,
        )

    def _ensure_collection_exists(self):
        collections = self.client.get_collections().collections
        collection_names = [c.name for c in collections]

        if self.collection_name not in collection_names:
            print(f"[KnowledgeBase] Creating new collection: {self.collection_name}")
            self.client.create_collection(
                collection_name=self.collection_name,
                vectors_config=VectorParams(
                    size=768,
                    distance=Distance.COSINE,
                ),
            )

    def add_documents(self, documents: List[Document]):
        if not documents:
            print("[KnowledgeBase] No documents to add.")
            return

        before = self.client.get_collection(self.collection_name).points_count
        print(f"[KnowledgeBase] Before insert: {before} points")

        self.vectorstore.add_documents(documents)

        after = self.client.get_collection(self.collection_name).points_count
        print(f"[KnowledgeBase] After insert: {after} points (+{after - before})")

        if after == before:
            print("[KnowledgeBase] WARNING: No points were added. Insertion may have failed.")

    def similarity_search(self, query: str, k: int = 4) -> List[Document]:
        docs = self.vectorstore.similarity_search(query, k=k)
        print(f"[KnowledgeBase] Retrieved {len(docs)} documents for query: {query[:80]}...")
        return docs

    def get_by_path(self, path: str, k: int = 2) -> List[Document]:
        """Exact lookup on metadata.path (supports / and \\ variants)."""
        path = path.replace("\\", "/")
        win_path = path.replace("/", "\\")

        qfilter = Filter(
            should=[
                FieldCondition(key="metadata.path", match=MatchValue(value=path)),
                FieldCondition(key="metadata.path", match=MatchValue(value=win_path)),
            ]
        )

        points, _ = self.client.scroll(
            collection_name=self.collection_name,
            scroll_filter=qfilter,
            limit=k,
            with_payload=True,
            with_vectors=False,
        )

        docs: List[Document] = []
        for p in points:
            payload = p.payload or {}
            text = payload.get("page_content") or ""
            meta = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
            meta = dict(meta)
            # Normalize path to forward slashes for the rest of the pipeline
            if meta.get("path"):
                meta["path"] = str(meta["path"]).replace("\\", "/")
            docs.append(Document(page_content=text, metadata=meta))

        print(f"[KnowledgeBase] get_by_path({path}) → {len(docs)} docs")
        return docs


    def similarity_search_with_filter(
        self,
        query: str,
        k: int = 4,
        metadata_filter: Optional[Dict[str, Any]] = None,
    ) -> List[Document]:
        if metadata_filter and "path" in metadata_filter:
            # Prefer exact scroll for path lookups (no useless embedding call)
            return self.get_by_path(str(metadata_filter["path"]), k=k)

        qfilter = self._build_filter(metadata_filter)
        try:
            docs = self.vectorstore.similarity_search(query, k=k, filter=qfilter)
        except TypeError:
            docs = self._client_search(query, k=k, qfilter=qfilter)

        print(
            f"[KnowledgeBase] Filtered search returned {len(docs)} docs "
            f"filter={metadata_filter}"
        )
        return docs


    def _build_filter(self, metadata_filter: Optional[Dict[str, Any]]):
        if not metadata_filter:
            return None

        should = []
        for key, value in metadata_filter.items():
            # Nested under metadata.*
            should.append(
                FieldCondition(key=f"metadata.{key}", match=MatchValue(value=value))
            )
            if key == "path" and isinstance(value, str):
                alt = value.replace("/", "\\") if "/" in value else value.replace("\\", "/")
                if alt != value:
                    should.append(
                        FieldCondition(key="metadata.path", match=MatchValue(value=alt))
                    )
        return Filter(should=should)

    def _client_search(self, query: str, k: int, qfilter) -> List[Document]:
        vector = self.embeddings.embed_query(query)
        results = self.client.search(
            collection_name=self.collection_name,
            query_vector=vector,
            query_filter=qfilter,
            limit=k,
            with_payload=True,
        )
        docs: List[Document] = []
        for r in results:
            payload = r.payload or {}
            text = (
                payload.get("page_content")
                or payload.get("text")
                or payload.get("content")
                or ""
            )
            metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else dict(payload)
            docs.append(Document(page_content=text, metadata=metadata))
        return docs