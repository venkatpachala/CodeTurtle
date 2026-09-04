"""Map hypotheses to Graphify MCP tool calls. Deterministic. No LLM."""

from __future__ import annotations

from typing import Iterable, List, Optional

from core.finding_validator import _is_source_path, _is_trivial, _path_in_allowed
from core.hypothesis import KEEP, PLAUSIBLE, REJECTED
from core.investigation.models import GraphOp, GraphifyCall, Hypothesis, InvestigationAsk
from core.pr_facts import extract_diff_symbols, is_lockfile, question_grounded_in_pr

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


_CALLEE_CLAIM = ("delete", "fail", "refresh", "drop ", "unlink", "rmtree", "commit(")


def wants_callees(h: Hypothesis) -> bool:
    if str(h.risk_hint or "") in ("mutation", "io"):
        return True
    blob = f"{h.claim} {h.title} {h.question}".lower()
    return any(k in blob for k in _CALLEE_CLAIM)


def _blocked_path(path: str) -> bool:
    p = (path or "").replace("\\", "/")
    if not p:
        return False
    if is_lockfile(p) or _is_trivial(p):
        return True
    return False


def plan_typed_asks(
    hypotheses: List[Hypothesis],
    *,
    pr_number: Optional[int] = None,
    repo: str = "",
) -> List[InvestigationAsk]:
    """Typed ops per hyp: get_node → find_callers → [find_callees] → find_tests.

    pr_impact once at the end. get_neighbors is a runtime fallback, not planned.
    """
    asks: List[InvestigationAsk] = []
    seen_node: set[str] = set()
    seen_callers: set[str] = set()
    seen_callees: set[str] = set()
    seen_tests: set[str] = set()

    for h in hypotheses:
        target = h.file or h.file_hint or ""
        if _blocked_path(target):
            continue
        label = ""
        if h.symbol:
            label = h.symbol.split(".")[-1] if "." in h.symbol else h.symbol
        if not label and target:
            label = file_label(target)
        if not label:
            continue
        if label not in seen_node:
            asks.append(
                InvestigationAsk(
                    op=GraphOp.GET_NODE,
                    ask="get_node",
                    file=target,
                    symbol=h.symbol or label,
                    hypothesis_id=h.id,
                )
            )
            seen_node.add(label)
        if label not in seen_callers:
            asks.append(
                InvestigationAsk(
                    op=GraphOp.FIND_CALLERS,
                    ask="find_callers",
                    file=target,
                    symbol=h.symbol or label,
                    hypothesis_id=h.id,
                    question=f"callers of {label}",
                )
            )
            seen_callers.add(label)
        if wants_callees(h) and label not in seen_callees:
            asks.append(
                InvestigationAsk(
                    op=GraphOp.FIND_CALLEES,
                    ask="find_callees",
                    file=target,
                    symbol=h.symbol or label,
                    hypothesis_id=h.id,
                    question=f"callees of {label}",
                )
            )
            seen_callees.add(label)
        test_key = (h.symbol or target or label).lower()
        if test_key not in seen_tests:
            asks.append(
                InvestigationAsk(
                    op=GraphOp.FIND_TESTS,
                    ask="find_tests",
                    file=target,
                    symbol=h.symbol or label,
                    hypothesis_id=h.id,
                    question=f"tests for {h.symbol or target or label}",
                )
            )
            seen_tests.add(test_key)

    if pr_number is not None and hypotheses:
        asks.append(
            InvestigationAsk(
                op=GraphOp.PR_IMPACT,
                ask="pr_impact",
                file="",
                hypothesis_id=hypotheses[0].id,
                pr_number=int(pr_number),
                repo=repo or None,
            )
        )
    return asks


def ask_to_graphify_call(
    ask: InvestigationAsk,
    *,
    pr_number: Optional[int] = None,
    repo: str = "",
) -> GraphifyCall:
    op = ask.op or GraphOp.GET_NEIGHBORS
    label = (ask.symbol or file_label(ask.file) or "").strip()
    hid = ask.hypothesis_id
    path = ask.file or ""
    if op == GraphOp.GET_NODE:
        return GraphifyCall(
            tool="get_node",
            op=op.value,
            label=label,
            hypothesis_id=hid,
            path=path,
            symbol=ask.symbol,
        )
    if op == GraphOp.FIND_CALLERS:
        return GraphifyCall(
            tool="query",
            op=op.value,
            label=label,
            hypothesis_id=hid,
            path=path,
            symbol=ask.symbol,
            question=ask.question or f"callers of {label}",
        )
    if op == GraphOp.FIND_CALLEES:
        return GraphifyCall(
            tool="query",
            op=op.value,
            label=label,
            hypothesis_id=hid,
            path=path,
            symbol=ask.symbol,
            question=ask.question or f"callees of {label}",
        )
    if op == GraphOp.FIND_TESTS:
        return GraphifyCall(
            tool="query",
            op=op.value,
            label=label,
            hypothesis_id=hid,
            path=path,
            symbol=ask.symbol,
            question=ask.question or f"tests for {ask.symbol or path or label}",
        )
    if op == GraphOp.PR_IMPACT:
        n = ask.pr_number if ask.pr_number is not None else pr_number
        return GraphifyCall(
            tool="get_pr_impact",
            op=op.value,
            label=str(n or ""),
            hypothesis_id=hid,
            path="",
            pr_number=int(n) if n is not None else None,
            repo=ask.repo or repo or None,
        )
    return GraphifyCall(
        tool="get_neighbors",
        op=GraphOp.GET_NEIGHBORS.value,
        label=label,
        hypothesis_id=hid,
        path=path,
        symbol=ask.symbol,
    )


def plan_graphify_calls(
    hypotheses: List[Hypothesis],
    *,
    pr_number: Optional[int] = None,
    repo: str = "",
) -> List[GraphifyCall]:
    """Typed asks mapped to MCP tools. Neighbors are a runtime fallback, not planned."""
    asks = plan_typed_asks(hypotheses, pr_number=pr_number, repo=repo)
    return [ask_to_graphify_call(a, pr_number=pr_number, repo=repo) for a in asks]


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


def _is_failure_path(finding: dict) -> bool:
    if finding.get("failure_path"):
        return True
    return str(finding.get("agent") or "") == "FailurePathExtractor"


def _pool_priority(finding: dict, files_changed: List[str], full_diff: str) -> tuple:
    st = str(finding.get("hypothesis_status") or KEEP)
    if st == REJECTED:
        return (9, 9)
    # Mutation failure-path hyps beat generic KEEP nits for the hop cap.
    if _is_failure_path(finding):
        return (0, 0)
    if st == KEEP:
        return (1, 0)
    # PLAUSIBLE: symbol-in-diff first, then token/file_hint
    if finding.get("symbol") and strip_ungrounded_symbol(
        finding.get("symbol"), files_changed, full_diff
    ):
        return (2, 0)
    if finding.get("file_hint") or finding.get("matched_tokens"):
        return (2, 1)
    return (2, 2)


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
                risk_hint=str(f.get("risk_hint") or "") or None,
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
        asks.append(
            InvestigationAsk(
                file=hit,
                symbol=sym,
                ask="find_callers",
                op=GraphOp.FIND_CALLERS,
            )
        )
        if len(asks) >= MAX_HYPOTHESES:
            break
    return asks
