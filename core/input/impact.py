"""Shared, bounded lexical impact context from immutable Git objects."""
from __future__ import annotations

import re
from pathlib import PurePosixPath

from core.input.snapshot import InputError
from core.change_units import unit_kind


class SnapshotImpactIndex:
    def __init__(self, provider, snapshot, changed_paths=(), *, max_files=200, max_chars=2_000_000):
        self.provider, self.snapshot = provider, snapshot
        self.changed = set(changed_paths)
        self.max_files = min(max_files, getattr(provider, "context_file_limit", max_files))
        self.max_chars = max_chars
        self.cache: dict[str, tuple[str, str]] = {}
        self.errors: list[str] = []
        self.loaded = False
        self.omitted = 0

    def _load(self):
        if self.loaded:
            return
        inventory = getattr(self.provider, "context_paths", self.provider.paths)
        paths = inventory(self.snapshot)
        skip = {"vendor", "node_modules", ".venv", "dist", "build"}
        parents = {PurePosixPath(p).parent for p in self.changed}
        paths = [p for p in paths if unit_kind(p) in {"source", "test"}
                 and not skip.intersection(PurePosixPath(p).parts)
                 and not re.search(r"(?:^|/)(?:\.env(?:\.|$)|credentials(?:\.|/)|secrets?(?:\.|/))", p, re.I)]
        paths.sort(key=lambda p: (p not in self.changed, PurePosixPath(p).parent not in parents,
                                  unit_kind(p) != "test", p))
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
        ranked = sorted(self.cache, key=lambda p: (p in self.changed, unit_kind(p) != "test"))
        for path in ranked:
            if tests_only and unit_kind(path) != "test":
                continue
            text, digest = self.cache[path]
            lines = text.splitlines()
            for number, line in enumerate(lines, 1):
                if needle.search(line):
                    if len(hits) == 20:
                        capped = True
                        break
                    first, last = max(1, number - 1), min(len(lines), number + 1)
                    hits.append({"path": path, "line": number, "text": line.strip()[:240], "content_sha256": digest,
                                 "changed": path in self.changed, "kind": unit_kind(path),
                                 "context": [{"line": n, "text": lines[n - 1][:240]}
                                             for n in range(first, last + 1)]})
                    break  # Prioritize distinct context paths over repeated hits in one file.
            if capped:
                break
        truncated = bool(self.omitted or self.errors or capped or getattr(self.provider, "context_inventory_limited", False))
        return {"symbol": symbol, "matches": hits, "n": len(hits),
                "text": "\n".join(f"{h['path']}:{h['line']}: {h['text']}" for h in hits),
                "source": "snapshot_lexical_search", "snapshot_id": self.snapshot.id,
                "revision_sha": self.snapshot.head_sha,
                "scanned_files": len(self.cache), "unreadable_paths": self.errors,
                "omitted_files": self.omitted, "hit_limit_reached": capped,
                "truncated": truncated, "status": "truncated" if truncated else "success" if hits else "empty",
                "limitations": ["Bounded lexical references, not resolved call-graph edges or proof of reachability."]}
