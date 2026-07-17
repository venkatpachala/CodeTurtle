from typing import List
from langchain_core.documents import Document

from core.repository_model import RepositoryModel
from core.chunker import PythonChunker
from core.document_builder import DocumentBuilder


class RepositoryIndexer:
    def __init__(self, repository_model: RepositoryModel):
        self.repository_model = repository_model
        self.python_chunker = PythonChunker()

    def to_documents(self) -> List[Document]:
        """Convert repository model into rich, structured documents."""
        documents = []

        for fm in self.repository_model.files:
            if fm.language.lower() == "python":
                chunks = self.python_chunker.chunk(fm)
            else:
                chunks = [self._simple_chunk(fm)]

            for chunk in chunks:
                doc = DocumentBuilder.build(chunk)
                documents.append(doc)

        print(f"[RepositoryIndexer] Created {len(documents)} rich documents")
        return documents

    def _simple_chunk(self, fm):
        from core.chunker import CodeChunk
        return CodeChunk(
            path=fm.path,
            language=fm.language,
            code=fm.content,
            preview=fm.preview,
            start_line=1,
            end_line=fm.line_count,
            chunk_index=0,
            chunk_type="module",
            symbols=[s.name for s in fm.symbols],
            imports=fm.imports
        )