from typing import List
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from core.repository_model import RepositoryModel


class RepositoryIndexer:
    def __init__(self, repository_model: RepositoryModel):
        self.repository_model = repository_model
        self.splitter = RecursiveCharacterTextSplitter(
            chunk_size=1000,
            chunk_overlap=200
        )

    def to_documents(self) -> List[Document]:
        """Convert repository model into rich, chunked documents."""
        documents = []
        total_chunks = 0

        for fm in self.repository_model.files:
            content = self._build_file_content(fm)
            chunks = self.splitter.split_text(content)

            for i, chunk in enumerate(chunks):
                documents.append(
                    Document(
                        page_content=chunk,
                        metadata={
                            "path": fm.path,
                            "language": fm.language,
                            "extension": fm.extension,
                            "chunk_index": i,
                            "line_count": fm.line_count,
                        },
                    )
                )
                total_chunks += 1

        print(f"[RepositoryIndexer] Created {total_chunks} chunks from {len(self.repository_model.files)} files")
        return documents

    def _build_file_content(self, fm) -> str:
        parts = [
            f"File: {fm.path}",
            f"Language: {fm.language}",
        ]

        if fm.symbols:
            parts.append("Symbols:")
            for symbol in fm.symbols:
                line_info = f" (line {symbol.line})" if symbol.line else ""
                parts.append(f"  - {symbol.type}: {symbol.name}{line_info}")

        if fm.imports:
            parts.append("Imports:")
            for imp in fm.imports[:20]:
                parts.append(f"  - {imp}")

        parts.append(f"\nPreview:\n{fm.preview}")

        return "\n".join(parts)