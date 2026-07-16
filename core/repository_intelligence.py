from pathlib import Path
from typing import List, Optional
import os
import ast
from datetime import datetime

from core.repository_model import FileModel, RepositoryModel
from core.knowledge_base import KnowledgeBase


class RepositoryIntelligence:
    """
    Dedicated pipeline for building and maintaining the Repository Knowledge Base.
    This runs independently from PR review.
    """

    def __init__(self, repo_path: str, repo_name: str):
        self.repo_path = Path(repo_path)
        self.repo_name = repo_name
        self.repository_model = RepositoryModel(repo_name=repo_name)

    def index_repository(self, force: bool = False) -> RepositoryModel:
        """Main entry point for indexing a repository."""
        print(f"[RepositoryIntelligence] Starting indexing for {self.repo_name}...")

        files = self._scan_files()
        print(f"[RepositoryIntelligence] Found {len(files)} relevant files.")

        file_models: List[FileModel] = []
        for file_path in files:
            file_model = self._extract_file_metadata(file_path)
            if file_model:
                file_models.append(file_model)

        self.repository_model.files = file_models
        self.repository_model.total_files = len(file_models)
        self.repository_model.indexed_at = datetime.now()

        self._embed_and_store(file_models)

        print(f"[RepositoryIntelligence] Successfully indexed {len(file_models)} files.")
        return self.repository_model

    def _scan_files(self) -> List[Path]:
        """Scan repository and return relevant files."""
        allowed_extensions = {".py", ".md", ".txt", ".rst", ".yaml", ".yml", ".json", ".toml"}
        excluded_dirs = {"node_modules", ".git", "__pycache__", "build", "dist", ".venv", "venv"}

        files: List[Path] = []
        for root, dirs, filenames in os.walk(self.repo_path):
            dirs[:] = [d for d in dirs if d not in excluded_dirs]

            for filename in filenames:
                if any(filename.endswith(ext) for ext in allowed_extensions):
                    full_path = Path(root) / filename
                    if full_path.stat().st_size < 500_000:   # Skip large files
                        files.append(full_path)
        return files

    def _extract_file_metadata(self, file_path: Path) -> Optional[FileModel]:
        """Extract structured metadata from a file."""
        try:
            content = file_path.read_text(encoding="utf-8", errors="ignore")
            extension = file_path.suffix.lower()
            language = self._detect_language(extension)

            file_model = FileModel(
                path=str(file_path.relative_to(self.repo_path)),
                language=language,
                extension=extension,
                size_bytes=len(content),
                preview=content[:600] + "..." if len(content) > 600 else content,
                line_count=len(content.splitlines()),
                last_modified=datetime.fromtimestamp(file_path.stat().st_mtime),
            )

            # AST parsing for Python files
            if extension == ".py":
                self._parse_python_ast(file_path, content, file_model)

            return file_model

        except Exception as e:
            print(f"Warning: Could not process {file_path}: {e}")
            return None

    def _detect_language(self, extension: str) -> str:
        mapping = {
            ".py": "Python",
            ".md": "Markdown",
            ".rst": "reStructuredText",
            ".yaml": "YAML",
            ".yml": "YAML",
            ".json": "JSON",
            ".toml": "TOML",
        }
        return mapping.get(extension, "Unknown")

    def _parse_python_ast(self, file_path: Path, content: str, file_model: FileModel):
        """Parse Python file using AST to extract structure."""
        try:
            tree = ast.parse(content, filename=str(file_path))

            for node in ast.walk(tree):
                if isinstance(node, ast.ClassDef):
                    file_model.classes.append(node.name)
                    # Capture class methods
                    for child in node.body:
                        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                            file_model.methods.append(child.name)

                elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    # Module-level functions (not inside class)
                    if not any(isinstance(parent, ast.ClassDef) for parent in ast.iter_child_nodes(node)):
                        file_model.functions.append(node.name)

                elif isinstance(node, ast.Import):
                    for alias in node.names:
                        file_model.imports.append(alias.name)

                elif isinstance(node, ast.ImportFrom):
                    if node.module:
                        file_model.imports.append(node.module)

        except SyntaxError:
            pass  # Skip files with syntax errors

    def _embed_and_store(self, file_models: List[FileModel]):
        """Generate embeddings and store in Qdrant using proper Document objects."""
        if not file_models:
            return

        from langchain_core.documents import Document
        from langchain_text_splitters import RecursiveCharacterTextSplitter

        kb = KnowledgeBase(collection_name=self.repo_name.replace("/", "_"))

        documents = []
        splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=200)

        for fm in file_models:
            # Split large files into chunks
            content = f"File: {fm.path}\nLanguage: {fm.language}\n\n{fm.preview}"
            chunks = splitter.split_text(content)

            for i, chunk in enumerate(chunks):
                documents.append(
                    Document(
                        page_content=chunk,
                        metadata={
                            "path": fm.path,
                            "language": fm.language,
                            "extension": fm.extension,
                            "chunk_index": i,
                        },
                    )
                )

        if documents:
            kb.add_documents(documents)
            print(f"[RepositoryIntelligence] Stored {len(documents)} chunks in Qdrant.")