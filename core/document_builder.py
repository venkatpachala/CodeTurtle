from typing import List
from langchain_core.documents import Document

from core.chunker import CodeChunk


class DocumentBuilder:
    """Builds rich LangChain Documents from CodeChunks."""

    @staticmethod
    def build(chunk: CodeChunk) -> Document:
        """Create a rich, structured document for embedding."""

        content = f"""File: {chunk.path}
Language: {chunk.language}
Chunk: {chunk.chunk_index}
Lines: {chunk.start_line}-{chunk.end_line}

Symbols:
{', '.join(chunk.symbols) if chunk.symbols else 'None'}

Imports:
{', '.join(chunk.imports) if chunk.imports else 'None'}

Code:
{chunk.code}
"""

        return Document(
            page_content=content,
            metadata={
                "path": chunk.path,
                "language": chunk.language,
                "chunk_index": chunk.chunk_index,
                "start_line": chunk.start_line,
                "end_line": chunk.end_line,
                "chunk_type": chunk.chunk_type,
                "symbols": chunk.symbols or [],
                "imports": chunk.imports or [],
            }
        )