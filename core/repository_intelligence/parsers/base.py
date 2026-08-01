from __future__ import annotations
from abc import ABC, abstractmethod
from pathlib import Path
from core.repository_intelligence.models import ParsedFile


class BaseParser(ABC):
    """Language-specific parser interface."""

    language: str = "unknown"

    @abstractmethod
    def can_parse(self, path: Path) -> bool:
        ...

    @abstractmethod
    def parse(self, path: Path, repo_name: str) -> ParsedFile:
        ...