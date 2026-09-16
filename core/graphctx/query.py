"""Graphify-by-identifier helpers. Symbols only — never paths or 'py'."""

from __future__ import annotations

from typing import Any, Dict, List

from core.graphctx.symbols import is_valid_symbol
from core.investigation.graphify_ops import hit_count, run_op
from core.repository_knowledge.graphify_mcp import GraphifyMCPError
from core.investigation.models import GraphOp

NEIGHBOR_CAP = 15
CHAR_CAP = 2000


def _truncate(text: str, n: int = CHAR_CAP) -> str:
    s = str(text or "")
    if len(s) <= n:
        return s
    return s[: n - 1] + "…"


def _items_text(items: List[Any]) -> str:
    parts: List[str] = []
    for it in (items or [])[:NEIGHBOR_CAP]:
        text = getattr(it, "text", None) or ""
        if not text and isinstance(it, dict):
            text = str(it.get("text") or it.get("preview") or "")
        if text:
            parts.append(str(text).strip())
    return _truncate("\n".join(parts))


def _ambiguous(items: List[Any]) -> bool:
    if not items:
        return False
    blob = " ".join(
        str(getattr(it, "text", None) or (it.get("text") if isinstance(it, dict) else "") or "")
        for it in items
    ).lower()
    if "ambiguous" in blob or "multiple matches" in blob:
        return True
    labels = set()
    for it in items:
        lab = getattr(it, "symbol", None)
        if lab is None and isinstance(it, dict):
            lab = it.get("symbol") or it.get("name")
        if lab:
            labels.add(str(lab))
    return len(items) > 1 and len(labels) > 1


def _guard(symbol: str) -> Dict[str, Any] | None:
    if not is_valid_symbol(symbol):
        return {"error": "invalid_symbol"}
    return None


def _run(client: Any, op: GraphOp, symbol: str) -> Dict[str, Any]:
    bad = _guard(symbol)
    if bad:
        return bad
    if client is None:
        return {"error": "no_graph"}
    try:
        items = run_op(client, op, symbol=symbol)
    except GraphifyMCPError as exc:
        return {"error": str(exc) or "graphify_error"}
    except Exception as exc:
        return {"error": type(exc).__name__}
    if _ambiguous(items):
        return {"error": "ambiguous"}
    text = _items_text(items)
    n = min(hit_count(items), NEIGHBOR_CAP) if items else 0
    if not text:
        return {"error": "not_found", "symbol": symbol}
    return {"symbol": symbol, "text": text, "n": n}


def graph_node(client: Any, symbol: str) -> Dict[str, Any]:
    return _run(client, GraphOp.GET_NODE, symbol)


def graph_callers(client: Any, symbol: str) -> Dict[str, Any]:
    return _run(client, GraphOp.FIND_CALLERS, symbol)


def graph_tests(client: Any, symbol: str) -> Dict[str, Any]:
    return _run(client, GraphOp.FIND_TESTS, symbol)
