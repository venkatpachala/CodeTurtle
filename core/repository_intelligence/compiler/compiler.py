from __future__ import annotations

from pathlib import Path
from typing import List, Optional

from core.repository_intelligence.models import RepositorySnapshot, ParsedFile
from core.repository_intelligence.compiler.scanner import RepositoryScanner
from core.repository_intelligence.parsers.python_parser import PythonParser
from core.repository_intelligence.parsers.base import BaseParser


class RepositoryCompiler:
    """
    Phase 1: Discovery + Python parsing.
    Produces a RepositorySnapshot with real symbols for .py files.
    """

    def __init__(self, repo_name: str, local_path: str):
        self.repo_name = repo_name
        self.local_path = Path(local_path).resolve()
        self.parsers: List[BaseParser] = [
            PythonParser(),
            # future: TypeScriptParser(), GoParser(), ...
        ]

    def compile(self) -> RepositorySnapshot:
        scanner = RepositoryScanner(self.local_path)
        paths = scanner.scan()

        files: List[ParsedFile] = []
        languages: set[str] = set()

        for path in paths:
            rel = str(path.relative_to(self.local_path)).replace("\\", "/")
            parser = self._get_parser(path)

            if parser:
                rel = str(path.relative_to(self.local_path)).replace("\\", "/")
                parsed = parser.parse(path, self.repo_name, relative_path=rel)
                files.append(parsed)
                languages.add(parsed.language)
            else:
                # Non-parsed file (md, yaml, etc.) — still keep metadata
                try:
                    content = path.read_text(encoding="utf-8", errors="ignore")
                except Exception:
                    content = ""
                lang = self._detect_language(path) or "unknown"
                languages.add(lang)
                files.append(
                    ParsedFile(
                        path=rel,
                        language=lang,
                        content=content,
                        line_count=content.count("\n") + 1 if content else 0,
                        size_bytes=path.stat().st_size,
                    )
                )

        return RepositorySnapshot(
            repo_name=self.repo_name,
            local_path=str(self.local_path),
            languages=sorted(languages),
            files=files,
        )

    def _get_parser(self, path: Path) -> Optional[BaseParser]:
        for p in self.parsers:
            if p.can_parse(path):
                return p
        return None

    def _detect_language(self, path: Path) -> Optional[str]:
        mapping = {
            ".py": "python",
            ".ts": "typescript",
            ".tsx": "typescript",
            ".js": "javascript",
            ".jsx": "javascript",
            ".go": "go",
            ".rs": "rust",
            ".java": "java",
            ".md": "markdown",
            ".yaml": "yaml",
            ".yml": "yaml",
            ".json": "json",
            ".toml": "toml",
        }
        return mapping.get(path.suffix.lower())