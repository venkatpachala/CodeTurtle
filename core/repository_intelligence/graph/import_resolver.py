"""
Phase 3: resolve Python import strings to in-repo File paths.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Dict, Iterable, List, Optional, Set, Tuple


# Very common stdlib top-levels — never link these as repo files
_STDLIB_ROOTS = {
    "abc", "ast", "asyncio", "base64", "builtins", "collections", "contextlib",
    "copy", "csv", "dataclasses", "datetime", "decimal", "enum", "functools",
    "glob", "hashlib", "http", "importlib", "inspect", "io", "itertools",
    "json", "logging", "math", "multiprocessing", "os", "pathlib", "pickle",
    "platform", "pprint", "re", "shutil", "socket", "sqlite3", "string",
    "subprocess", "sys", "tempfile", "threading", "time", "typing",
    "typing_extensions", "unittest", "urllib", "uuid", "warnings", "weakref",
    "xml", "zipfile",
}


@dataclass
class ImportEdge:
    source_path: str          # e.g. "graphify/cli.py"
    target_path: str          # e.g. "graphify/utils.py"
    raw_import: str           # original import text
    import_kind: str          # "module" | "from"


def _normalize_path(p: str) -> str:
    return str(PurePosixPath(p.replace("\\", "/")))


def _module_to_candidates(module: str) -> List[str]:
    """
    foo.bar.baz  →  foo/bar/baz.py
                    foo/bar/baz/__init__.py
                    foo/bar.py          (prefix fallbacks handled by caller set)
    """
    if not module or module.startswith("."):
        return []

    parts = module.split(".")
    base = "/".join(parts)
    return [
        f"{base}.py",
        f"{base}/__init__.py",
    ]


def _relative_to_candidates(
    source_path: str,
    module: str,
) -> List[str]:
    """
    Resolve relative imports: from .foo import bar, from ..pkg import x
    """
    if not module.startswith("."):
        return []

    # Count leading dots
    dots = 0
    for ch in module:
        if ch == ".":
            dots += 1
        else:
            break
    remainder = module[dots:].strip(".")

    src = PurePosixPath(_normalize_path(source_path))
    # package dir = parent of file; each extra dot goes up one more
    pkg = src.parent
    for _ in range(max(0, dots - 1)):
        pkg = pkg.parent if str(pkg) not in ("", ".") else PurePosixPath(".")

    if remainder:
        base = pkg / "/".join(remainder.split("."))
    else:
        base = pkg

    base_s = str(base).replace("\\", "/")
    if base_s in ("", "."):
        return [f"{remainder.replace('.', '/')}.py"] if remainder else []

    return [
        f"{base_s}.py",
        f"{base_s}/__init__.py",
    ]


_IMPORT_RE = re.compile(
    r"^\s*(?:from\s+([\w.]+)\s+import|import\s+([\w.]+))",
    re.MULTILINE,
)


def parse_import_modules(import_entry: str) -> Tuple[str, str]:
    """
    Accept either:
      - raw line: 'from foo.bar import Baz'
      - dotted module already extracted: 'foo.bar'
    Returns (module, kind)
    """
    text = import_entry.strip()
    m = _IMPORT_RE.match(text)
    if m:
        if m.group(1):
            return m.group(1), "from"
        return m.group(2), "module"

    # already a module path like "foo.bar"
    if re.match(r"^[\w.]+$", text):
        return text, "module"

    return text, "module"


class ImportResolver:
    """
    Map each file's import list → in-repo File paths.
    """

    def __init__(self, file_paths: Iterable[str]):
        # normalized path set + index by stem for quick checks
        self.paths: Set[str] = {_normalize_path(p) for p in file_paths}
        # also index without leading ./
        self.paths = {p[2:] if p.startswith("./") else p for p in self.paths}

    def _pick_existing(self, candidates: List[str]) -> Optional[str]:
        for c in candidates:
            c = _normalize_path(c)
            if c in self.paths:
                return c
        return None

    def resolve_one(self, source_path: str, import_entry: str) -> Optional[ImportEdge]:
        source_path = _normalize_path(source_path)
        module, kind = parse_import_modules(import_entry)

        if not module:
            return None

        # skip obvious stdlib root
        root = module.lstrip(".").split(".")[0]
        if root in _STDLIB_ROOTS and not module.startswith("."):
            return None

        candidates: List[str] = []
        if module.startswith("."):
            candidates = _relative_to_candidates(source_path, module)
        else:
            candidates = _module_to_candidates(module)
            # also try progressively shorter prefixes: foo.bar.baz → foo/bar.py
            parts = module.split(".")
            for i in range(len(parts) - 1, 0, -1):
                prefix = "/".join(parts[:i])
                candidates.extend([f"{prefix}.py", f"{prefix}/__init__.py"])

        target = self._pick_existing(candidates)
        if not target or target == source_path:
            return None

        return ImportEdge(
            source_path=source_path,
            target_path=target,
            raw_import=import_entry,
            import_kind=kind,
        )

    def resolve_all(
        self,
        file_imports: Dict[str, List[str]],
    ) -> List[ImportEdge]:
        """
        file_imports: { "graphify/cli.py": ["os", "graphify.utils", "from .models import X"], ... }
        """
        edges: List[ImportEdge] = []
        seen: Set[Tuple[str, str]] = set()

        for source, imports in file_imports.items():
            for raw in imports or []:
                edge = self.resolve_one(source, raw)
                if edge is None:
                    continue
                key = (edge.source_path, edge.target_path)
                if key in seen:
                    continue
                seen.add(key)
                edges.append(edge)

        return edges