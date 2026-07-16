from pathlib import Path
from typing import List, Optional
import os
import ast
import json
from datetime import datetime
import hashlib

from core.repository_model import FileModel, RepositoryModel, Symbol
from core.knowledge_base import KnowledgeBase
from core.repository_indexer import RepositoryIndexer   # We'll create this next
from core.repository_analyzer import RepositoryAnalyzer
from core.repository_persistence import RepositoryPersistence

class RepositoryPersistence:
    """Handles persistence of the RepositoryModel."""

    def __init__(self, repo_path: Path):
        self.repo_path = repo_path
        self.dot_codeturtle = self.repo_path / ".codeturtle"

    def save_repository_model(self, repository_model: RepositoryModel):
        """Save RepositoryModel to .codeturtle/"""
        self.dot_codeturtle.mkdir(parents=True, exist_ok=True)
        path = self.dot_codeturtle / "repository_model.json"
        with open(path, "w", encoding="utf-8") as f:
            f.write(repository_model.model_dump_json(indent=2))


class RepositoryIntelligence:
    """
    Dedicated pipeline for building the Repository Knowledge Base.
    """

    def __init__(self, repo_path: str, repo_name: str):
        self.repo_path = Path(repo_path)
        self.repo_name = repo_name
        self.repository_model = RepositoryModel(repo_name=repo_name)
        self.persistence = RepositoryPersistence(repo_path)

    def index_repository(self, force: bool = False) -> RepositoryModel:
        """Main entry point."""
        print(f"[RepositoryIntelligence] Indexing {self.repo_name}...")

        files = self._scan_files()

        file_models: List[FileModel] = []
        for file_path in files:
            if force or self._should_reindex(file_path):
                file_model = self._extract_file_metadata(file_path)
                if file_model:
                    file_models.append(file_model)

        self.repository_model.files = file_models
        self.repository_model.total_files = len(file_models)
        self.repository_model.indexed_at = datetime.now()

        # Build symbol index
        self._build_symbol_index()

        # Analyze
        analyzer = RepositoryAnalyzer(self.repository_model)
        analyzer.analyze()

        # Persist model
        self.persistence.save_repository_model(self.repository_model)

        # Embed and store
        self._embed_and_store(file_models)

        print(f"[RepositoryIntelligence] Successfully indexed {len(file_models)} files.")
        return self.repository_model

    def _scan_files(self) -> List[Path]:
        allowed_extensions = {".py", ".md", ".txt", ".rst", ".yaml", ".yml", ".json", ".toml"}
        excluded_dirs = {"node_modules", ".git", "__pycache__", "build", "dist", ".venv", "venv"}

        files: List[Path] = []
        for root, dirs, filenames in os.walk(self.repo_path):
            dirs[:] = [d for d in dirs if d not in excluded_dirs]

            for filename in filenames:
                if any(filename.endswith(ext) for ext in allowed_extensions):
                    full_path = Path(root) / filename
                    if full_path.stat().st_size < 500_000:
                        files.append(full_path)
        return files

    def _should_reindex(self, file_path: Path) -> bool:
        """Placeholder for real incremental indexing."""
        return True

    def _extract_file_metadata(self, file_path: Path) -> Optional[FileModel]:
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

            if extension == ".py":
                self._parse_python_ast(file_path, content, file_model)

            return file_model

        except Exception as e:
            print(f"Warning: Could not process {file_path}: {e}")
            return None

    def _parse_python_ast(self, file_path: Path, content: str, file_model: FileModel):
        """Improved AST parsing."""
        try:
            tree = ast.parse(content, filename=str(file_path))

            for node in tree.body:
                if isinstance(node, ast.ClassDef):
                    file_model.symbols.append(
                        Symbol(
                            name=node.name,
                            type="class",
                            line=node.lineno,
                            docstring=ast.get_docstring(node),
                        )
                    )
                    for child in node.body:
                        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                            file_model.symbols.append(
                                Symbol(
                                    name=child.name,
                                    type="method",
                                    line=child.lineno,
                                    docstring=ast.get_docstring(child),
                                )
                            )

                elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    file_model.symbols.append(
                        Symbol(
                            name=node.name,
                            type="function",
                            line=node.lineno,
                            docstring=ast.get_docstring(node),
                        )
                    )

        except SyntaxError:
            pass

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

    def _build_symbol_index(self):
        """Build simple symbol index (fully qualified name → symbol)."""
        for fm in self.repository_model.files:
            for symbol in fm.symbols:
                key = f"{fm.path}::{symbol.name}"
                self.repository_model.symbol_index[key] = symbol

    def _embed_and_store(self, file_models: List[FileModel]):
        """Use RepositoryIndexer to store in Qdrant."""
        if not file_models:
            return
        indexer = RepositoryIndexer(self.repository_model)
        documents = indexer.to_documents()

        kb = KnowledgeBase(collection_name=self.repo_name.replace("/", "_"))
        kb.add_documents(documents)
        print(f"[RepositoryIntelligence] Stored {len(documents)} chunks in Qdrant.")