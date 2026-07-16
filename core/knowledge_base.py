from langchain_qdrant import QdrantVectorStore
from langchain_ollama import OllamaEmbeddings
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams
from langchain_core.documents import Document
from typing import List

class KnowledgeBase:
    def __init__(self, collection_name: str):
        self.collection_name = collection_name
        self.embeddings = OllamaEmbeddings(model="nomic-embed-text")
        self.client = QdrantClient(
            host="localhost",
            port=6333,
        )
        
        # Ensure collection exists
        self._ensure_collection_exists()

        self.vectorstore = QdrantVectorStore(
            client=self.client,
            collection_name=collection_name,
            embedding=self.embeddings,
        )

    def _ensure_collection_exists(self):
        """Create collection if it doesn't exist."""
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
        """Add documents to the collection with verification."""
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
        """Search for relevant documents."""
        docs = self.vectorstore.similarity_search(query, k=k)
        print(f"[KnowledgeBase] Retrieved {len(docs)} documents for query: {query[:80]}...")
        return docs