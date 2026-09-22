"""Bundle-scoped tools. Graphify calls take identifier symbols only."""

from __future__ import annotations

from pathlib import Path
import re
from typing import Any, Dict, Optional

from core.graphctx.query import graph_callees, graph_callers, graph_node, graph_tests
from core.graphctx.symbols import is_valid_symbol
from core.pr_facts import normalize_path
from core.runtime.models import Bundle
from core.verification.diff_index import DiffIndex


class BundleTools:
    def __init__(
        self,
        bundle: Bundle,
        *,
        index: Optional[DiffIndex] = None,
        client: Any = None,
        repo_dir: Optional[str] = None,
    ):
        self.bundle = bundle
        self.index = index
        self.client = client
        self.repo_dir = Path(repo_dir).resolve() if repo_dir else None
        self._search_cache: Dict[tuple[str, bool], Dict[str, Any]] = {}
        self.allowed = {normalize_path(p) for p in (bundle.paths or []) if p}

    def _in_bundle(self, path: str) -> Optional[str]:
        n = normalize_path(path)
        if not n:
            return None
        if n in self.allowed:
            return n
        base = n.split("/")[-1]
        for a in self.allowed:
            if a == n or a.endswith("/" + n) or n.endswith("/" + a):
                return a
            if base and a.split("/")[-1] == base:
                return a
        return None

    def read_hunk(self, path: str) -> Dict[str, Any]:
        resolved = self._in_bundle(path)
        if not resolved:
            return {"error": "not_in_bundle"}
        excerpts = []
        for u in self.bundle.units or []:
            up = normalize_path(
                str(u.get("path") if isinstance(u, dict) else getattr(u, "path", "") or "")
            )
            if up != resolved:
                continue
            excerpt = u.get("excerpt") if isinstance(u, dict) else getattr(u, "excerpt", "")
            if excerpt:
                excerpts.append(str(excerpt))
        if excerpts:
            text = "\n\n".join(excerpts)
            if len(text) > 2000:
                text = text[:1999] + "…"
            return {"path": resolved, "text": text}
        if self.index is not None:
            hunks = self.index.hunks_for(resolved)
            if hunks:
                text = "\n".join(h.raw for h in hunks)
                if len(text) > 2000:
                    text = text[:1999] + "…"
                return {"path": resolved, "text": text}
        return {"error": "no_hunk", "path": resolved}

    def graph_node(self, symbol: str) -> Dict[str, Any]:
        if not is_valid_symbol(symbol):
            return {"error": "invalid_symbol"}
        return graph_node(self.client, symbol)

    def graph_callers(self, symbol: str) -> Dict[str, Any]:
        if not is_valid_symbol(symbol):
            return {"error": "invalid_symbol"}
        if self.client is None:
            return self._search_repository(symbol, tests_only=False)
        return graph_callers(self.client, symbol)

    def graph_tests(self, symbol: str) -> Dict[str, Any]:
        if not is_valid_symbol(symbol):
            return {"error": "invalid_symbol"}
        if self.client is None:
            return self._search_repository(symbol, tests_only=True)
        return graph_tests(self.client, symbol)

    def graph_callees(self, symbol: str) -> Dict[str, Any]:
        if not is_valid_symbol(symbol):
            return {"error": "invalid_symbol"}
        if self.client is None:
            return self._search_repository(symbol, tests_only=False)
        return graph_callees(self.client, symbol)

    def callee_contract(self, symbol: str) -> Dict[str, Any]:
        """Return a bounded source contract for a Ruby class method.

        This is intentionally narrow: it is used only as evidence for a
        changed call-site and never permits arbitrary repository dumping.
        """
        if self.repo_dir is None or not self.repo_dir.is_dir():
            return {"error": "no_checkout"}
        raw = str(symbol or "").strip()
        if "." not in raw:
            return {"error": "invalid_symbol"}
        receiver, method = raw.rsplit(".", 1)
        if not re.fullmatch(r"[A-Z]\w*(?:::[A-Z]\w*)*", receiver) or not re.fullmatch(r"[a-z_]\w*[!?=]?", method):
            return {"error": "invalid_symbol"}
        stem = re.sub(r"(?<!^)(?=[A-Z])", "_", receiver.split("::")[-1]).lower() + ".rb"
        skip = {".git", "vendor", "node_modules", "tmp"}
        for path in self.repo_dir.rglob(stem):
            if any(part in skip for part in path.parts):
                continue
            try:
                if path.stat().st_size > 1_000_000:
                    continue
                lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
                starts = [i for i, line in enumerate(lines) if re.match(rf"\s*def\s+self\.{re.escape(method)}\b", line)]
                if not starts:
                    continue
                # Include the named method plus the dynamic dispatcher, which
                # is where image operations select animated implementations.
                for i, line in enumerate(lines):
                    if re.match(r"\s*def\s+self\.optimize\b", line):
                        starts.append(i)
                    if method in {"downsize", "resize"} and re.match(
                        r"\s*def\s+self\.(?:downsize|resize)_instructions_animated\b", line
                    ):
                        starts.append(i)
                selected = []
                seen_lines = set()
                for start in sorted(set(starts))[:4]:
                    for line_no in range(start, min(start + 16, len(lines))):
                        if line_no not in seen_lines:
                            selected.append(lines[line_no])
                            seen_lines.add(line_no)
                rel = path.relative_to(self.repo_dir).as_posix()
                return {"symbol": raw, "path": rel, "text": "\n".join(selected)[:3500], "source": "callee_contract"}
            except OSError:
                continue
        return {"error": "not_found", "symbol": raw}

    def _search_repository(self, symbol: str, *, tests_only: bool) -> Dict[str, Any]:
        """Bounded lexical fallback when structural graph evidence is unavailable."""
        key = (symbol, tests_only)
        if key in self._search_cache:
            return dict(self._search_cache[key])
        root = self.repo_dir
        if root is None or not root.is_dir():
            return {"error": "no_graph_or_checkout"}
        needle = symbol.split(".")[-1]
        extensions = {".py", ".js", ".jsx", ".ts", ".tsx", ".rb", ".go", ".rs", ".java", ".kt"}
        skip_dirs = {".git", ".venv", "node_modules", "vendor", "dist", "build", "target"}
        hits = []
        scanned = 0
        for path in root.rglob("*"):
            if scanned >= 2500 or len(hits) >= 20:
                break
            if not path.is_file() or path.suffix.lower() not in extensions:
                continue
            try:
                rel = path.relative_to(root).as_posix()
            except ValueError:
                continue
            if any(part in skip_dirs for part in path.parts):
                continue
            low = rel.lower()
            is_test = "test" in Path(rel).name.lower() or "/tests/" in f"/{low}/" or "/test/" in f"/{low}/"
            if tests_only and not is_test:
                continue
            scanned += 1
            try:
                if path.stat().st_size > 1_000_000:
                    continue
                for line_no, line in enumerate(path.read_text(encoding="utf-8", errors="ignore").splitlines(), start=1):
                    if needle in line:
                        hits.append(f"{rel}:{line_no}: {line.strip()[:240]}")
                        if len(hits) >= 20:
                            break
            except OSError:
                continue
        result = (
            {"symbol": symbol, "text": "\n".join(hits), "n": len(hits), "source": "repository_search"}
            if hits else {"error": "not_found", "symbol": symbol, "source": "repository_search"}
        )
        self._search_cache[key] = result
        return dict(result)

    def dispatch(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        name = str((payload or {}).get("tool") or "").strip()
        if name == "read_hunk":
            return self.read_hunk(str(payload.get("path") or payload.get("file") or ""))
        if name == "graph_node":
            return self.graph_node(str(payload.get("symbol") or payload.get("label") or ""))
        if name == "graph_callers":
            return self.graph_callers(str(payload.get("symbol") or payload.get("label") or ""))
        if name == "graph_callees":
            return self.graph_callees(str(payload.get("symbol") or payload.get("label") or ""))
        if name == "callee_contract":
            return self.callee_contract(str(payload.get("symbol") or payload.get("label") or ""))
        if name == "graph_tests":
            return self.graph_tests(str(payload.get("symbol") or payload.get("label") or ""))
        return {"error": "unknown_tool"}
