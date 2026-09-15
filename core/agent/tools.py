"""Bundle-scoped tools. Graphify calls take identifier symbols only."""

from __future__ import annotations

from typing import Any, Dict, Optional

from core.graphctx.query import graph_callers, graph_node, graph_tests
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
    ):
        self.bundle = bundle
        self.index = index
        self.client = client
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
        return graph_callers(self.client, symbol)

    def graph_tests(self, symbol: str) -> Dict[str, Any]:
        if not is_valid_symbol(symbol):
            return {"error": "invalid_symbol"}
        return graph_tests(self.client, symbol)

    def dispatch(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        name = str((payload or {}).get("tool") or "").strip()
        if name == "read_hunk":
            return self.read_hunk(str(payload.get("path") or payload.get("file") or ""))
        if name == "graph_node":
            return self.graph_node(str(payload.get("symbol") or payload.get("label") or ""))
        if name == "graph_callers":
            return self.graph_callers(str(payload.get("symbol") or payload.get("label") or ""))
        if name == "graph_tests":
            return self.graph_tests(str(payload.get("symbol") or payload.get("label") or ""))
        return {"error": "unknown_tool"}
