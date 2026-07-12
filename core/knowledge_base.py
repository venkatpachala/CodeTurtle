from langchain_ollama import OllamaEmbeddings
from langchain_qdrant import QdrantVectorStore
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams
from langchain_text_splitters import RecursiveCharacterTextSplitter
from pathlib import Path

class KnowledgeBase:
    def __init__(self, collection_name: str):
        self.collection_name = collection_name
        self.embeddings = OllamaEmbeddings(model="nomic-embed-text")
        
        # Connect to local Qdrant (persistent storage)
        self.client = QdrantClient(path="./qdrant_data")

        # Create collection if it doesn't exist
        if not self.client.collection_exists(collection_name):
            self.client.create_collection(
                collection_name=collection_name,
                vectors_config=VectorParams(size=768, distance=Distance.COSINE),
            )

        # Use the modern QdrantVectorStore
        self.vectorstore = QdrantVectorStore(
            client=self.client,
            collection_name=collection_name,
            embedding=self.embeddings,
        )

    def add_documents(self, documents: list):
        """Add documents to the knowledge base"""
        text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=1000,
            chunk_overlap=200,
            separators=["\n\n", "\n", " ", ""]
        )
        splits = text_splitter.split_documents(documents)
        self.vectorstore.add_documents(splits)
        print(f"[green]Added {len(splits)} chunks to knowledge base: {self.collection_name}[/green]")

    def similarity_search(self, query: str, k: int = 5):
        """Search relevant code/documents from knowledge base"""
        return self.vectorstore.similarity_search(query, k=k)