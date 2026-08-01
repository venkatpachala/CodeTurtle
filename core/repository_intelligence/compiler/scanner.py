from __future__ import annotations

from pathlib import Path
from typing import List, Set

# Paths / patterns we never want to index
IGNORE_DIRS: Set[str] = {
    ".git",
    ".hg",
    ".svn",
    "__pycache__",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".tox",
    ".venv",
    "venv",
    "env",
    "node_modules",
    "dist",
    "build",
    "target",
    ".idea",
    ".vscode",
    ".codeturtle",
}

IGNORE_SUFFIXES: Set[str] = {
    ".pyc",
    ".pyo",
    ".so",
    ".dll",
    ".exe",
    ".bin",
    ".o",
    ".a",
    ".class",
    ".jar",
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".ico",
    ".svg",
    ".woff",
    ".woff2",
    ".ttf",
    ".eot",
    ".map",
    ".min.js",
    ".min.css",
}

MAX_FILE_SIZE = 1_000_000  # 1 MB


class RepositoryScanner:
    def __init__(self, root: Path):
        self.root = root.resolve()

    def scan(self) -> List[Path]:
        files: List[Path] = []
        for path in self.root.rglob("*"):
            if not path.is_file():
                continue
            if self._should_ignore(path):
                continue
            try:
                if path.stat().st_size > MAX_FILE_SIZE:
                    continue
            except OSError:
                continue
            files.append(path)
        return files

    def _should_ignore(self, path: Path) -> bool:
        # Directory parts
        for part in path.parts:
            if part in IGNORE_DIRS:
                return True
            if part.startswith(".") and part not in {".github"}:
                # allow .github, ignore other dot dirs
                if part != path.name:  # it's a directory component
                    return True

        # Suffixes
        name = path.name.lower()
        for suf in IGNORE_SUFFIXES:
            if name.endswith(suf):
                return True

        return False