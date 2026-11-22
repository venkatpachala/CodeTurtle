"""Shared, bounded lexical impact context from immutable Git objects."""
from __future__ import annotations

import re
from pathlib import PurePosixPath

from core.input.snapshot import InputError


class SnapshotImpactIndex:
    def __init__(self, provider, snapshot, changed_paths=(), *, max_files=200, max_chars=2_000_000):
        self.provider, self.snapshot = provider, snapshot
        self.changed = set(changed_paths)
        self.max_files, self.max_chars = max_files, max_chars
        self.cache: dict[str, tuple[str, str]] = {}
        self.errors: list[str] = []
        self.loaded = False
        self.omitted = 0

    def _load(self):
        if self.loaded:
            return
        paths = self.provider.paths(self.snapshot)
        extensions = {".py", ".js", ".jsx", ".ts", ".tsx", ".rb", ".go", ".rs", ".java"}
        skip = {"vendor", "node_modules", ".venv", "dist", "build"}
        paths = [p for p in paths if PurePosixPath(p).suffix in extensions and not skip.intersection(PurePosixPath(p).parts)]
        paths.sort(key=lambda p: (p not in self.changed, p))
        used = 0
        for path in paths[:self.max_files]:
            try:
                source = self.provider.read(self.snapshot, path)
                text = source.content.decode("utf-8", errors="replace")
                if used+len(text) > self.max_chars:
                    self.errors.append(path)
                    continue
                self.cache[path] = (text, source.content_sha256)
                used += len(text)
            except InputError:
                self.errors.append(path)
        self.omitted = max(0, len(paths)-self.max_files)
        self.loaded = True

    def search(self, symbol: str, *, tests_only=False) -> dict:
        if not re.fullmatch(r"[A-Za-z_]\w*(?:(?:\.|::)[A-Za-z_]\w*)*", symbol):
            return {"error": "invalid_symbol", "status": "denied"}
        try:
            self._load()
        except InputError:
            return {"error": "impact_index_unavailable", "status": "error"}
        needle = re.compile(r"\b"+re.escape(re.split(r"\.|::", symbol)[-1])+r"\b")
        hits = []
        capped = False
        for path, (text, digest) in self.cache.items():
            if tests_only and "test" not in path.lower():
                continue
            for number, line in enumerate(text.splitlines(), 1):
                if needle.search(line):
                    if len(hits) == 20:
                        capped = True
                        break
                    hits.append({"path": path, "line": number, "text": line.strip()[:240], "content_sha256": digest})
            if capped:
                break
        truncated = bool(self.omitted or self.errors or capped)
        return {"symbol": symbol, "matches": hits, "n": len(hits),
                "text": "\n".join(f"{h['path']}:{h['line']}: {h['text']}" for h in hits),
                "source": "snapshot_lexical_search", "snapshot_id": self.snapshot.id,
                "scanned_files": len(self.cache), "unreadable_paths": self.errors,
                "omitted_files": self.omitted, "hit_limit_reached": capped,
                "truncated": truncated, "status": "truncated" if truncated else "success" if hits else "empty",
                "limitations": ["Bounded lexical references, not resolved call-graph edges or proof of reachability."]}
