from abc import ABC, abstractmethod
from typing import List
from dataclasses import dataclass

from core.repository_model import FileModel, Symbol


@dataclass
class CodeChunk:
    """A meaningful, AST-aware chunk of code."""

    path: str
    language: str

    code: str
    preview: str

    start_line: int
    end_line: int

    chunk_index: int
    chunk_type: str

    symbols: List[str] = None
    imports: List[str] = None


class BaseChunker(ABC):
    @abstractmethod
    def chunk(self, file_model: FileModel) -> List[CodeChunk]:
        pass


class PythonChunker(BaseChunker):
    """Improved sequential AST-aware chunking for Python files."""

    def chunk(self, file_model: FileModel) -> List[CodeChunk]:
        chunks = []
        if not file_model.content.strip():
            return chunks

        lines = file_model.content.splitlines()

        try:
            import ast
            tree = ast.parse(file_model.content, filename=file_model.path)
        except SyntaxError:
            return self._fallback_chunk(file_model)

        previous_end = 1

        for node in tree.body:
            if not hasattr(node, 'lineno'):
                continue

            start = node.lineno
            end = getattr(node, 'end_lineno', start)

            # Emit module chunk for uncovered code before this node
            if previous_end < start:
                code = "\n".join(lines[previous_end-1:start-1])
                if code.strip():
                    chunks.append(CodeChunk(
                        path=file_model.path,
                        language=file_model.language,
                        code=code,
                        preview=code[:300],
                        start_line=previous_end,
                        end_line=start-1,
                        chunk_index=len(chunks),
                        chunk_type="module",
                        symbols=[],
                        imports=file_model.imports
                    ))

            # Emit the main node chunk (class or function)
            if isinstance(node, ast.ClassDef):
                chunk_type = "class"
                name = node.name
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                chunk_type = "function"
                name = node.name
            else:
                previous_end = end + 1
                continue

            code = "\n".join(lines[start-1:end])

            chunks.append(CodeChunk(
                path=file_model.path,
                language=file_model.language,
                code=code,
                preview=code[:400],
                start_line=start,
                end_line=end,
                chunk_index=len(chunks),
                chunk_type=chunk_type,
                symbols=[name],
                imports=file_model.imports
            ))

            previous_end = end + 1

        # Final module chunk for trailing code
        if previous_end <= file_model.line_count:
            code = "\n".join(lines[previous_end-1:file_model.line_count])
            if code.strip():
                chunks.append(CodeChunk(
                    path=file_model.path,
                    language=file_model.language,
                    code=code,
                    preview=code[:300],
                    start_line=previous_end,
                    end_line=file_model.line_count,
                    chunk_index=len(chunks),
                    chunk_type="module",
                    symbols=[],
                    imports=file_model.imports
                ))

        return chunks

    def _fallback_chunk(self, file_model: FileModel) -> List[CodeChunk]:
        """Simple fallback for syntax errors."""
        return [CodeChunk(
            path=file_model.path,
            language=file_model.language,
            code=file_model.content,
            preview=file_model.preview,
            start_line=1,
            end_line=file_model.line_count,
            chunk_index=0,
            chunk_type="module",
            symbols=[s.name for s in file_model.symbols],
            imports=file_model.imports
        )]