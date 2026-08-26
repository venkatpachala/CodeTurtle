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
            path="qdrant_data"
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

    def get_by_path(self, path: str, k: int = 4) -> List[Document]:
        """Exact lookup on metadata.path (supports / and \\ variants)."""
        clean_path = path.replace("\\", "/").lstrip("./")
        win_path = clean_path.replace("/", "\\")

        qfilter = Filter(
            should=[
                FieldCondition(key="metadata.path", match=MatchValue(value=clean_path)),
                FieldCondition(key="metadata.path", match=MatchValue(value=win_path)),
                FieldCondition(key="metadata.path", match=MatchValue(value=f"./{clean_path}")),
                FieldCondition(key="metadata.path", match=MatchValue(value=f".\\{win_path}")),
            ]
        )

        try:
            points, _ = self.client.scroll(
                collection_name=self.collection_name,
                scroll_filter=qfilter,
                limit=k,
                with_payload=True,
                with_vectors=False,
            )
        except Exception as e:
            print(f"[KnowledgeBase] get_by_path failed for {clean_path}: {e}")
            points = []

        docs: List[Document] = []
        for p in points:
            payload = p.payload or {}
            text = (
                payload.get("page_content")
                or payload.get("text")
                or payload.get("content")
                or ""
            )
            meta = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
            meta = dict(meta)
            # Normalize path to forward slashes for the rest of the pipeline
            if meta.get("path"):
                meta["path"] = str(meta["path"]).replace("\\", "/").lstrip("./")
            else:
                meta["path"] = clean_path
            meta.setdefault("retrieval_type", "path")
            docs.append(Document(page_content=text, metadata=meta))

        print(f"[KnowledgeBase] get_by_path({path}) -> {len(docs)} docs")
        return docs

    def search_by_metadata_symbol(self, name: str, k: int = 4) -> List[Document]:
        """Search for exact symbol in metadata.symbols or metadata.symbol."""
        if not name:
            return []

        qfilter = Filter(
            should=[
                FieldCondition(key="metadata.symbols", match=MatchValue(value=name)),
                FieldCondition(key="metadata.symbol", match=MatchValue(value=name)),
            ]
        )

        try:
            points, _ = self.client.scroll(
                collection_name=self.collection_name,
                scroll_filter=qfilter,
                limit=k,
                with_payload=True,
                with_vectors=False,
            )
        except Exception as e:
            print(f"[KnowledgeBase] search_by_metadata_symbol failed for {name}: {e}")
            points = []

        docs: List[Document] = []
        for p in points:
            payload = p.payload or {}
            text = (
                payload.get("page_content")
                or payload.get("text")
                or payload.get("content")
                or ""
            )
            meta = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
            meta = dict(meta)
            if meta.get("path"):
                meta["path"] = str(meta["path"]).replace("\\", "/").lstrip("./")
            meta.setdefault("retrieval_type", "symbol")
            docs.append(Document(page_content=text, metadata=meta))

        print(f"[KnowledgeBase] search_by_metadata_symbol({name}) -> {len(docs)} docs")
        return docs

    def keyword_search(self, keyword: str, k: int = 4) -> List[Document]:
        """Search page_content for exact keyword."""
        if not keyword:
            return []

        points = []
        try:
            from qdrant_client.models import MatchText
            qfilter = Filter(
                should=[
                    FieldCondition(key="page_content", match=MatchText(text=keyword)),
                ]
            )
            points, _ = self.client.scroll(
                collection_name=self.collection_name,
                scroll_filter=qfilter,
                limit=k,
                with_payload=True,
                with_vectors=False,
            )
        except Exception as e:
            print(f"[KnowledgeBase] keyword_search filter failed for {keyword}: {e}")

        docs: List[Document] = []
        for p in points:
            payload = p.payload or {}
            text = (
                payload.get("page_content")
                or payload.get("text")
                or payload.get("content")
                or ""
            )
            meta = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
            meta = dict(meta)
            if meta.get("path"):
                meta["path"] = str(meta["path"]).replace("\\", "/").lstrip("./")
            meta.setdefault("retrieval_type", "keyword")
            docs.append(Document(page_content=text, metadata=meta))

        print(f"[KnowledgeBase] keyword_search({keyword}) -> {len(docs)} docs")
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

    def recreate_collection(self):
        """Delete collection if it exists, then create empty with correct vector config."""
        collections = self.client.get_collections().collections
        names = [c.name for c in collections]

        if self.collection_name in names:
            print(f"[KnowledgeBase] Deleting collection: {self.collection_name}")
            self.client.delete_collection(self.collection_name)

        print(f"[KnowledgeBase] Creating collection: {self.collection_name}")
        self.client.create_collection(
            collection_name=self.collection_name,
            vectors_config=VectorParams(
                size=768,  # nomic-embed-text
                distance=Distance.COSINE,
            ),
        )

        # Rebuild LangChain wrapper against empty collection
        self.vectorstore = QdrantVectorStore(
            client=self.client,
            collection_name=self.collection_name,
            embedding=self.embeddings,
        )