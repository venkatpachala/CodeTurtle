from typing import List, Dict
from pathlib import Path

from core.repository_model import RepositoryModel, FileModel


class RepositoryAnalyzer:
    """Analyzes the repository and enriches the RepositoryModel with higher-level insights."""

    def __init__(self, repository_model: RepositoryModel):
        self.repository_model = repository_model

    def analyze(self):
        """Run all analysis passes."""
        self._build_dependency_graph()
        self._compute_statistics()
        self._build_symbol_index()
        # Future: architecture summary, package boundaries, etc.

    def _build_dependency_graph(self):
        """Extract dependencies from imports (simple version)."""
        for fm in self.repository_model.files:
            for imp in fm.imports:
                # Simple heuristic: add to dependencies
                fm.dependencies.append(imp)

    def _compute_statistics(self):
        """Compute repository-wide statistics."""
        total_symbols = sum(len(f.symbols) for f in self.repository_model.files)
        print(f"[RepositoryAnalyzer] Total symbols detected: {total_symbols}")

    def _build_symbol_index(self):
        """Build fully qualified symbol index."""
        for fm in self.repository_model.files:
            for symbol in fm.symbols:
                key = f"{fm.path}::{symbol.name}"
                self.repository_model.symbol_index[key] = symbol