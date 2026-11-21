"""Bundle tool adapter that never falls back to mutable checkout content."""
from __future__ import annotations

import re
from pathlib import PurePosixPath

from core.agent.tools import BundleTools
from core.input.snapshot import GitSnapshotProvider, InputError, ReviewSnapshot


class SnapshotBundleTools(BundleTools):
    def __init__(self, bundle, *, index, provider: GitSnapshotProvider, snapshot: ReviewSnapshot):
        super().__init__(bundle, index=index)
        self.provider = provider
        self.snapshot = snapshot

    def read_source(self, path: str) -> dict:
        resolved = self._in_bundle(path)
        if not resolved:
            return {"error": "outside_bundle", "status": "denied"}
        try:
            source = self.provider.read(self.snapshot, resolved)
        except InputError as exc:
            return {"error": str(exc), "status": "error"}
        lines = source.content.decode("utf-8", errors="replace").splitlines()
        starts = [int(unit.get("start_line", 1) if isinstance(unit, dict) else getattr(unit, "start_line", 1))
                  for unit in self.bundle.units]
        start = max(0, min(starts or [1]) - 21)
        selected = lines[start:start + 100]
        text = "\n".join(f"{i}: {line}" for i, line in enumerate(selected, start=start + 1))
        truncated = start > 0 or start + len(selected) < len(lines) or len(text) > 5000
        return {"path": resolved, "text": text[:5000], "source": "git_snapshot",
                "snapshot_id": self.snapshot.id, "revision_sha": source.revision_sha,
                "content_sha256": source.content_sha256, "truncated": truncated,
                "status": "truncated" if truncated else "success"}

    def graph_node(self, symbol: str) -> dict:
        return self._search_repository(symbol, tests_only=False)

    def callee_contract(self, symbol: str) -> dict:
        return {"error": "snapshot_callee_contract_not_supported", "status": "denied"}

    def _search_repository(self, symbol: str, *, tests_only: bool) -> dict:
        key = (symbol, tests_only)
        if key in self._search_cache:
            return dict(self._search_cache[key])
        if not re.fullmatch(r"[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*", symbol):
            return {"error": "invalid_symbol", "status": "denied"}
        needle = re.compile(rf"\b{re.escape(symbol.rsplit('.', 1)[-1])}\b")
        hits, errors, scanned = [], [], 0
        extensions = {".py", ".js", ".jsx", ".ts", ".tsx", ".rb", ".go", ".rs", ".java"}
        skip = {"vendor", "node_modules", ".venv", "dist", "build"}
        try:
            paths = self.provider.paths(self.snapshot)
        except InputError as exc:
            return {"error": str(exc), "status": "error"}
        eligible = [path for path in paths if PurePosixPath(path).suffix in extensions
                    and not skip.intersection(PurePosixPath(path).parts)
                    and (not tests_only or "test" in path.lower())]
        # Search changed paths first, then a deterministic bounded repository slice.
        eligible.sort(key=lambda path: (path not in self.allowed, path))
        for path in eligible[:200]:
            scanned += 1
            try:
                source = self.provider.read(self.snapshot, path)
            except InputError:
                errors.append(path)
                continue
            for number, line in enumerate(source.content.decode("utf-8", errors="replace").splitlines(), 1):
                if needle.search(line):
                    hits.append({"path": path, "line": number, "text": line.strip()[:240],
                                 "content_sha256": source.content_sha256})
                    if len(hits) >= 20:
                        break
            if len(hits) >= 20:
                break
        truncated = len(eligible) > scanned or bool(errors) or len(hits) >= 20
        result = {"symbol": symbol, "matches": hits, "n": len(hits),
                  "text": "\n".join(f"{hit['path']}:{hit['line']}: {hit['text']}" for hit in hits),
                  "source": "snapshot_lexical_search", "snapshot_id": self.snapshot.id,
                  "scanned_files": scanned, "unreadable_paths": errors, "truncated": truncated,
                  "status": "truncated" if truncated else "success" if hits else "empty",
                  "limitations": ["Lexical references are not resolved call-graph edges."]}
        self._search_cache[key] = result
        return dict(result)
