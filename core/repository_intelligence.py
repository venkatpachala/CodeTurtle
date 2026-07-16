from pathlib import Path
from typing import List, Optional
import os
from datetime import datetime

from core.repository_model import FileModel, RepositoryModel
from core.knowledge_base import KnowledgeBase


class RepositoryIntelligence:
    """
    Dedicated pipeline for building and maintaining the Repository Knowledge Base.
    This runs independently from the PR review pipeline.
    """

    def __init__(self, repo_path: str, repo_name: str):
        self.repo_path = Path(repo_path)
        self.repo_name = repo_name
        self.repository_model = RepositoryModel(repo_name=repo_name)
        self.kb = None

    def index_repository(self, force: bool = False) -> RepositoryModel:
        """
        Main entry point to build the repository knowledge base.
        """
        print(f"[RepositoryIntelligence] Starting indexing for {self.repo_name}...")

        # 1. Scan repository
        files = self._scan_files()
        print(f"[RepositoryIntelligence] Found {len(files)} relevant files.")

        # 2. Extract structured metadata
        file_models: List[FileModel] = []
        for file_path in files:
            file_model = self._extract_file_metadata(file_path)
            if file_model:
                file_models.append(file_model)

        self.repository_model.files = file_models
        self.repository_model.total_files = len(file_models)
        self.repository_model.indexed_at = datetime.now()

        # 3. Generate embeddings and store in Qdrant
        self._embed_and_store(file_models)

        print(f"[RepositoryIntelligence] Successfully indexed {len(file_models)} files.")
        return self.repository_model

    def _scan_files(self) -> List[Path]:
        """Scan repository and return relevant text/code files."""
        allowed_extensions = {".py", ".md", ".txt", ".rst", ".yaml", ".yml", ".json", ".toml", ".cfg", ".ini"}
        excluded_dirs = {"node_modules", ".git", "__pycache__", "build", "dist", ".venv", "venv", ".idea", ".vscode"}

        files: List[Path] = []
        for root, dirs, filenames in os.walk(self.repo_path):
            # Remove excluded directories in-place
            dirs[:] = [d for d in dirs if d not in excluded_dirs]

            for filename in filenames:
                if any(filename.endswith(ext) for ext in allowed_extensions):
                    files.append(Path(root) / filename)
        return files

    def _extract_file_metadata(self, file_path: Path) -> Optional[FileModel]:
        """Extract structured information from a single file."""
        try:
            content = file_path.read_text(encoding="utf-8", errors="ignore")
            extension = file_path.suffix.lower()
            language = self._detect_language(extension)

            return FileModel(
                path=str(file_path.relative_to(self.repo_path)),
                language=language,
                extension=extension,
                size_bytes=len(content),
                summary=content[:800] + "..." if len(content) > 800 else content,
                last_modified=datetime.fromtimestamp(file_path.stat().st_mtime),
            )
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
            ".cfg": "Config",
            ".ini": "Config",
        }
        return mapping.get(extension, "Unknown")

    def _embed_and_store(self, file_models: List[FileModel]):
        """Generate embeddings and store in Qdrant."""
        if not file_models:
            return

        self.kb = KnowledgeBase(collection_name=self.repo_name.replace("/", "_"))

        # Convert FileModel objects into documents for embedding
        documents = []
        for fm in file_models:
            content = f"File: {fm.path}\nLanguage: {fm.language}\n\n{fm.summary}"
            documents.append({"page_content": content, "metadata": {"path": fm.path}})

        # Reuse existing KnowledgeBase add_documents method
        self.kb.add_documents(documents)