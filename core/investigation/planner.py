"""Map hypotheses to Graphify MCP tool calls. Deterministic. No LLM."""

from __future__ import annotations

from typing import Iterable, List, Optional

from core.finding_validator import _is_source_path, _is_trivial, _path_in_allowed
from core.hypothesis import KEEP, PLAUSIBLE, REJECTED
from core.investigation.models import GraphifyCall, Hypothesis, InvestigationAsk
from core.pr_facts import extract_diff_symbols, question_grounded_in_pr

MAX_HYPOTHESES = 3
MAX_GRAPHIFY_CALLS_IN_INVESTIGATE = 6
TIMEOUT_S = 45.0


def file_label(path: str) -> str:
    p = (path or "").replace("\\", "/").strip("/")
    return p.split("/")[-1] or p


def path_in_pr(path: str, files_changed: Iterable[str]) -> Optional[str]:
    return _path_in_allowed(path, files_changed or [])


def is_investigable_path(path: str, files_changed: Iterable[str]) -> Optional[str]:
    hit = path_in_pr(path, files_changed)
    if not hit:
        return None
    if _is_trivial(hit):
        return None
    if not _is_source_path(hit):
        return None
    return hit


def strip_ungrounded_symbol(
    symbol: Optional[str],
    files_changed: List[str],
    full_diff: str,
) -> Optional[str]:
    s = (symbol or "").strip()
    if not s:
        return None
    if not question_grounded_in_pr(s, files_changed, full_diff):
        return None
    return s


def plan_graphify_calls(
    hypotheses: List[Hypothesis],
    *,
    pr_number: Optional[int] = None,
    repo: str = "",
) -> List[GraphifyCall]:
    """For each hypothesis: get_node, get_neighbors, optional query. Impact once."""
    calls: List[GraphifyCall] = []
    seen_node: set[str] = set()
    seen_neigh: set[str] = set()
    seen_query: set[str] = set()

    for h in hypotheses:
        labels: List[str] = []
        if h.symbol:
            labels.append(h.symbol.split(".")[-1] if "." in h.symbol else h.symbol)
        target = h.file or h.file_hint or ""
        if target:
            labels.append(file_label(target))
        for lab in dict.fromkeys(l for l in labels if l):
            if lab not in seen_node:
                calls.append(
                    GraphifyCall(
                        tool="get_node",
                        label=lab,
                        hypothesis_id=h.id,
                        path=target,
                        symbol=h.symbol,
                    )
                )
                seen_node.add(lab)
            if lab not in seen_neigh:
                calls.append(
                    GraphifyCall(
                        tool="get_neighbors",
                        label=lab,
                        hypothesis_id=h.id,
                        path=target,
                        symbol=h.symbol,
                    )
                )
                seen_neigh.add(lab)

        if h.symbol or (h.question or "").strip():
            q = (h.question or "").strip() or (
                f"callers of {h.symbol or file_label(target or 'symbol')} "
                f"in {target or 'diff'}"
            )
            key = q.strip().lower()
            if key not in seen_query:
                calls.append(
                    GraphifyCall(
                        tool="query",
                        label=h.symbol or file_label(target or "symbol"),
                        hypothesis_id=h.id,
                        path=target,
                        symbol=h.symbol,
                        question=q,
                    )
                )
                seen_query.add(key)

    if pr_number is not None:
        calls.append(
            GraphifyCall(
                tool="get_pr_impact",
                label=str(pr_number),
                hypothesis_id=hypotheses[0].id if hypotheses else None,
                path="",
                pr_number=int(pr_number),
                repo=repo or None,
            )
        )
    return calls


def asks_to_hypotheses(
    asks: Iterable,
    *,
    files_changed: List[str],
    full_diff: str,
    start_index: int = 1,
) -> List[Hypothesis]:
    hyps: List[Hypothesis] = []
    for raw in asks or []:
        if hasattr(raw, "model_dump"):
            d = raw.model_dump()
        elif isinstance(raw, dict):
            d = dict(raw)
        else:
            continue
        path = is_investigable_path(str(d.get("file") or ""), files_changed)
        if not path:
            continue
        symbol = strip_ungrounded_symbol(d.get("symbol"), files_changed, full_diff)
        ask = str(d.get("ask") or "neighbors")
        hid = f"H{start_index + len(hyps)}"
        hyps.append(
            Hypothesis(
                id=hid,
                claim=f"{ask} for {path}",
                file=path,
                symbol=symbol,
                question=(
                    f"who imports {path}"
                    if "import" in ask.lower()
                    else f"neighbors of {symbol or file_label(path)}"
                ),
                status="open",
                title=f"investigate {file_label(path)}",
            )
        )
        if len(hyps) >= MAX_HYPOTHESES:
            break
    return hyps


def _pool_priority(finding: dict, files_changed: List[str], full_diff: str) -> tuple:
    st = str(finding.get("hypothesis_status") or KEEP)
    if st == REJECTED:
        return (9, 9)
    if st == KEEP:
        return (0, 0)
    # PLAUSIBLE: symbol-in-diff first, then token/file_hint
    if finding.get("symbol") and strip_ungrounded_symbol(
        finding.get("symbol"), files_changed, full_diff
    ):
        return (1, 0)
    if finding.get("file_hint") or finding.get("matched_tokens"):
        return (1, 1)
    return (1, 2)


def findings_to_hypotheses(
    findings: List[dict],
    *,
    files_changed: List[str],
    full_diff: str,
    max_n: int = MAX_HYPOTHESES,
) -> List[Hypothesis]:
    ordered = sorted(
        list(findings or []),
        key=lambda f: _pool_priority(f if isinstance(f, dict) else {}, files_changed, full_diff),
    )
    hyps: List[Hypothesis] = []
    for f in ordered:
        if len(hyps) >= max_n:
            break
        if not isinstance(f, dict):
            continue
        kind = str(f.get("hypothesis_status") or KEEP)
        if kind == REJECTED:
            continue
        path = is_investigable_path(
            str(f.get("file") or f.get("file_hint") or ""), files_changed
        )
        if not path:
            path = is_investigable_path(str(f.get("file_hint") or ""), files_changed)
        if path and _is_trivial(path):
            path = None
        if not path:
            if kind != PLAUSIBLE:
                continue
            if not f.get("symbol"):
                continue
        if kind != PLAUSIBLE and not _is_thin(f) and not f.get("needs_investigation"):
            continue
        symbol = strip_ungrounded_symbol(f.get("symbol"), files_changed, full_diff)
        question = str(f.get("question") or "")
        if question and not question_grounded_in_pr(question, files_changed, full_diff):
            question = ""
        hid = f"H{len(hyps) + 1}"
        hyps.append(
            Hypothesis(
                id=hid,
                claim=str(f.get("claim") or f.get("title") or ""),
                file=path or "",
                file_hint=str(f.get("file_hint") or path or "") or None,
                symbol=symbol,
                question=question,
                status="open",
                needs_investigation=True,
                finding_id=str(f.get("id") or ""),
                category=str(f.get("category") or "review"),
                title=str(f.get("title") or ""),
                hypothesis_kind=kind,
            )
        )
    return hyps


def _is_thin(finding: dict) -> bool:
    """True when we only have a path, not neighbors / callers / a hunk snippet."""
    if finding.get("evidence_ids") or finding.get("investigation_snippets"):
        return False
    ev = finding.get("evidence") or []
    if isinstance(ev, str):
        ev = [ev]
    kinds = " ".join(str(x).lower() for x in ev)
    if any(k in kinds for k in ("neighbor", "caller", "hunk", "impact", "graphify")):
        return False
    return True


def deterministic_investigate_asks(
    files_changed: List[str],
    full_diff: str,
) -> List[InvestigationAsk]:
    """Up to 3 asks: neighbors of changed source files / diff symbols."""
    asks: List[InvestigationAsk] = []
    symbols = extract_diff_symbols(full_diff or "")
    for path in files_changed or []:
        hit = is_investigable_path(path, files_changed)
        if not hit:
            continue
        stem = file_label(hit).rsplit(".", 1)[0]
        sym = None
        for s in symbols:
            if strip_ungrounded_symbol(s, [hit], full_diff) and (
                stem.lower() in s.lower() or s.lower() in (full_diff or "").lower()
            ):
                sym = s
                break
        asks.append(InvestigationAsk(file=hit, symbol=sym, ask="neighbors"))
        if len(asks) >= MAX_HYPOTHESES:
            break
    return asks
