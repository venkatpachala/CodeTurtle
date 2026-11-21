"""Bundle tool adapter that never falls back to mutable checkout content."""
from __future__ import annotations

import re
from pathlib import PurePosixPath

from core.agent.tools import BundleTools
from core.input.snapshot import GitSnapshotProvider, InputError, ReviewSnapshot
from core.pr_facts import normalize_path


class SnapshotBundleTools(BundleTools):
    supports_scoped_source = True
    def __init__(self, bundle, *, index, provider: GitSnapshotProvider, snapshot: ReviewSnapshot):
        super().__init__(bundle, index=index)
        self.provider = provider
        self.snapshot = snapshot

    def read_source(self, path: str, *, symbol: str = "") -> dict:
        resolved = self._in_bundle(path)
        if not resolved:
            return {"error": "outside_bundle", "status": "denied"}
        try:
            source = self.provider.read(self.snapshot, resolved)
        except InputError as exc:
            return {"error": str(exc), "status": "error"}
        lines = source.content.decode("utf-8", errors="replace").splitlines()
        starts = [int(unit.get("start_line", 1) if isinstance(unit, dict) else getattr(unit, "start_line", 1))
                  for unit in self.bundle.units
                  if normalize_path(unit.get("path", "") if isinstance(unit, dict) else getattr(unit, "path", "")) == resolved]
        from core.input.excerpts import capture_excerpt
        excerpt = capture_excerpt("\n".join(lines), resolved, symbol=symbol,
                                  anchor=max(1, min(starts or [1])), max_lines=100, max_chars=4000)
        text = "\n".join(f"{i}: {line}" for i, line in enumerate(excerpt.text.splitlines(), start=excerpt.start_line))
        truncated = not excerpt.complete or bool(excerpt.unresolved_dependencies) or len(text) > 5000
        return {"path": resolved, "text": text[:5000], "source": "git_snapshot",
                "snapshot_id": self.snapshot.id, "revision_sha": source.revision_sha,
                "content_sha256": source.content_sha256, "truncated": truncated,
                "scope": excerpt.scope, "scope_symbol": excerpt.symbol,
                "start_line": excerpt.start_line, "end_line": excerpt.start_line + len(excerpt.text.splitlines()) - 1,
                "unresolved_dependencies": list(excerpt.unresolved_dependencies),
                "limitations": ["Completeness refers only to the declared source scope; runtime contracts may require more context."],
                "status": "truncated" if truncated else "success"}

    def graph_node(self, symbol: str) -> dict:
        return self._search_repository(symbol, tests_only=False)

    def callee_contract(self, symbol: str) -> dict:
        if "." not in symbol:
            return {"error": "invalid_symbol", "status": "denied"}
        receiver, method = symbol.rsplit(".", 1)
        if not re.fullmatch(r"[A-Z]\w*(?:::[A-Z]\w*)*", receiver) or not re.fullmatch(r"[a-z_]\w*[!?=]?", method):
            return {"error": "invalid_symbol", "status": "denied"}
        stem = re.sub(r"(?<!^)(?=[A-Z])", "_", receiver.split("::")[-1]).lower() + ".rb"
        try:
            matches = [p for p in self.provider.paths(self.snapshot) if PurePosixPath(p).name == stem
                       and not set(PurePosixPath(p).parts) & {"vendor", "node_modules", "tmp"}]
            if len(matches) != 1:
                return {"error": "ambiguous_or_missing_callee", "status": "denied"}
            path = matches[0]
            source = self.provider.read(self.snapshot, path)
        except InputError:
            return {"error": "callee_source_unavailable", "status": "error"}
        lines = source.content.decode("utf-8", errors="replace").splitlines()
        names = {method, "optimize"}
        if method in {"downsize", "resize"}:
            names.update({"downsize_instructions_animated", "resize_instructions_animated"})
        starts = [n for n, line in enumerate(lines)
                  if any(re.match(rf"\s*def\s+self\.{re.escape(name)}\b", line) for name in names)]
        if not starts:
            return {"error": "callee_not_found", "status": "empty"}
        numbers = sorted({n for start in starts[:4] for n in range(start, min(start + 16, len(lines)))})
        text = "\n".join(f"{n+1}: {lines[n]}" for n in numbers)
        return {"symbol": symbol, "path": path, "text": text[:3500], "source": "snapshot_callee_contract",
                "snapshot_id": self.snapshot.id, "revision_sha": source.revision_sha,
                "content_sha256": source.content_sha256, "truncated": True, "status": "truncated",
                "limitations": ["Bounded Ruby method excerpts; not a resolved dispatch proof."]}

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
