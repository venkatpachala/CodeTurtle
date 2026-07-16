from typing import List
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from core.repository_model import RepositoryModel


class RepositoryIndexer:
    """
    Converts the rich RepositoryModel into vector store documents.
    This is the bridge between Repository Intelligence and Knowledge Base.
    """

    def __init__(self, repository_model: RepositoryModel):
        self.repository_model = repository_model
        self.splitter = RecursiveCharacterTextSplitter(
            chunk_size=1000,
            chunk_overlap=200
        )

    def to_documents(self) -> List[Document]:
        """Convert repository model into rich, chunked documents."""
        documents = []

        for fm in self.repository_model.files:
            # Build rich content for this file
            content = self._build_file_content(fm)

            # Split into chunks
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
                            "file_size": fm.size_bytes,
                        },
                    )
                )

        return documents

    def _build_file_content(self, fm) -> str:
        """Build rich content for a file (for embedding)."""
        parts = [
            f"File: {fm.path}",
            f"Language: {fm.language}",
        ]

        # Add symbols
        if fm.symbols:
            parts.append("Symbols:")
            for symbol in fm.symbols:
                line_info = f" (line {symbol.line})" if symbol.line else ""
                parts.append(f"  - {symbol.type}: {symbol.name}{line_info}")
                if symbol.docstring:
                    parts.append(f"    Docstring: {symbol.docstring[:200]}...")

        # Add imports
        if fm.imports:
            parts.append("Imports:")
            for imp in fm.imports[:20]:  # Limit for brevity
                parts.append(f"  - {imp}")

        # Add preview
        parts.append(f"\nPreview:\n{fm.preview}")

        return "\n".join(parts)