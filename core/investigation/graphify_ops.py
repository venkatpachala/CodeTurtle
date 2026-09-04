"""Thin typed Graphify ops on existing MCP. One MCP call per run_op."""

from __future__ import annotations

from typing import Any, List, Optional

from core.investigation.models import EvidenceItem, GraphOp
from core.pr_facts import is_lockfile, normalize_path
from core.repository_knowledge.graphify_mcp import GraphifyMCPError


def _basename(path: str) -> str:
    p = normalize_path(path or "")
    return p.split("/")[-1] if p else ""


def _label(symbol: str = "", path: Optional[str] = None) -> str:
    s = (symbol or "").strip()
    if s:
        return s.split(".")[-1] if "." in s else s
    return _basename(path or "")


def _item(
    *,
    kind: str,
    text: str,
    path: str = "",
    symbol: Optional[str] = None,
) -> Optional[EvidenceItem]:
    blob = str(text or "").strip()
    if not blob:
        return None
    return EvidenceItem(
        id="",
        source="graphify",
        kind=kind,  # type: ignore[arg-type]
        path=path or "",
        symbol=symbol,
        text=blob[:4000],
    )


def _from_result(result: Any, *, kind: str, path: str, symbol: Optional[str]) -> List[EvidenceItem]:
    if result is None:
        return []
    items: List[EvidenceItem] = []
    if isinstance(result, list):
        for raw in result:
            if isinstance(raw, EvidenceItem):
                items.append(raw)
                continue
            if isinstance(raw, dict):
                ev = _item(
                    kind=str(raw.get("kind") or kind),
                    text=str(raw.get("text") or raw.get("preview") or ""),
                    path=str(raw.get("path") or path),
                    symbol=raw.get("symbol") or raw.get("name") or symbol,
                )
                if ev:
                    items.append(ev)
                continue
            text = getattr(raw, "raw_text", None) or getattr(raw, "text", None) or str(raw)
            ev = _item(kind=kind, text=str(text), path=path, symbol=symbol)
            if ev:
                items.append(ev)
        return items
    text = ""
    if hasattr(result, "raw_text"):
        text = getattr(result, "raw_text", "") or ""
    elif hasattr(result, "raw"):
        raw = getattr(result, "raw", None) or {}
        if isinstance(raw, dict):
            text = str(raw.get("text") or "")
        if not text:
            text = str(getattr(result, "label", "") or "")
    elif isinstance(result, dict):
        text = str(result.get("text") or result.get("preview") or result.get("raw_text") or "")
    else:
        text = str(result or "")
    extra_bits: List[str] = []
    for n in getattr(result, "neighbors", None) or []:
        name = getattr(n, "label", None) or getattr(n, "id", None) or ""
        npath = getattr(n, "path", None) or ""
        if name or npath:
            extra_bits.append(f"{npath} {name}".strip())
    if extra_bits and extra_bits[0] not in (text or ""):
        text = (text + "\n" + "\n".join(extra_bits)).strip()
    ev = _item(kind=kind, text=text, path=path, symbol=symbol)
    return [ev] if ev else []


def hit_count(items: List[EvidenceItem]) -> int:
    if not items:
        return 0
    n = 0
    for it in items:
        lines = [ln for ln in (it.text or "").splitlines() if ln.strip()]
        n += max(len(lines), 1) if (it.text or "").strip() else 0
    return n or len(items)


def run_op(
    client: Any,
    op: GraphOp | str,
    *,
    symbol: str = "",
    path: Optional[str] = None,
    pr_number: Optional[int] = None,
    repo: Optional[str] = None,
) -> List[EvidenceItem]:
    """One existing MCP tool. Empty list on miss/error. Never raises."""
    try:
        op_e = op if isinstance(op, GraphOp) else GraphOp(str(op))
    except ValueError:
        op_e = GraphOp.GET_NEIGHBORS
    label = _label(symbol, path)
    path_n = normalize_path(path or "")
    if path_n and is_lockfile(path_n) and op_e not in (GraphOp.PR_IMPACT,):
        print(f"[Investigate] skip op={op_e.value} path={path_n} reason=lockfile")
        return []
    try:
        if op_e == GraphOp.GET_NODE:
            if not label:
                return []
            node = client.get_node(label)
            return _from_result(node, kind="node", path=path_n, symbol=symbol or label)
        if op_e == GraphOp.FIND_CALLERS:
            if not label:
                return []
            meth = getattr(client, "find_callers", None)
            if callable(meth):
                return _from_result(
                    meth(label), kind="callers", path=path_n, symbol=symbol or label
                )
            try:
                result = client.get_neighbors(label, relation_filter="call")
            except TypeError:
                result = client.get_neighbors(label)
            return _from_result(result, kind="callers", path=path_n, symbol=symbol or label)
        if op_e == GraphOp.FIND_CALLEES:
            if not label:
                return []
            meth = getattr(client, "find_callees", None)
            if callable(meth):
                return _from_result(
                    meth(label), kind="callees", path=path_n, symbol=symbol or label
                )
            try:
                result = client.get_neighbors(label, relation_filter="call")
            except TypeError:
                result = client.get_neighbors(label)
            return _from_result(result, kind="callees", path=path_n, symbol=symbol or label)
        if op_e == GraphOp.FIND_TESTS:
            target = symbol or path_n or label
            if not target:
                return []
            meth = getattr(client, "find_tests", None)
            if callable(meth):
                return _from_result(
                    meth(target), kind="tests", path=path_n, symbol=symbol or label
                )
            result = client.query(f"tests for {target}", depth=3)
            return _from_result(result, kind="tests", path=path_n, symbol=symbol or label)
        if op_e == GraphOp.PR_IMPACT:
            if pr_number is None:
                return []
            impact = client.get_pr_impact(int(pr_number), repo=repo)
            return _from_result(impact, kind="pr_impact", path=path_n, symbol=symbol)
        if op_e == GraphOp.GET_NEIGHBORS:
            if not label:
                return []
            if path_n and is_lockfile(path_n):
                return []
            neigh = client.get_neighbors(label)
            return _from_result(neigh, kind="neighbors", path=path_n, symbol=symbol or label)
    except GraphifyMCPError as exc:
        print(f"[Investigate] op={op_e.value} error={type(exc).__name__}")
        return []
    except Exception as exc:
        print(f"[Investigate] op={op_e.value} error={type(exc).__name__}")
        return []
    return []
