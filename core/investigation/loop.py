"""Bounded investigation: Graphify hops on real changed files, then re-validate."""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from core.finding_validator import filter_findings
from core.hypothesis import KEEP, PLAUSIBLE, UNRESOLVED
from core.investigation.graphify_ops import hit_count, run_op
from core.investigation.models import EvidenceItem, GraphOp, GraphifyCall, Hypothesis, InvestigationAsk
from core.investigation.planner import (
    MAX_GRAPHIFY_CALLS_IN_INVESTIGATE,
    MAX_HYPOTHESES,
    TIMEOUT_S,
    asks_to_hypotheses,
    file_label,
    findings_to_hypotheses,
    is_investigable_path,
    plan_typed_asks,
    strip_ungrounded_symbol,
)
from core.finding_validator import _is_source_path, _is_trivial
from core.pr_facts import extract_diff_symbols, normalize_path, question_grounded_in_pr
from core.repository_knowledge.graphify_mcp import GraphifyMCPError


def _skip(reason: str, state: dict) -> dict:
    print(f"[Investigate] skip reason={reason}")
    report = {
        "ran": False,
        "skipped": True,
        "reason": reason,
        "hops": 0,
        "calls": 0,
        "hypotheses": 0,
    }
    return {
        "hypotheses": list(state.get("hypotheses") or []),
        "investigation_evidence": [],
        "investigation_report": report,
        "traces": [{"agent": "Investigate", "output": f"skip reason={reason}"}],
    }


def _evidence_id(n: int) -> str:
    return f"E{n}"


def execute_call(provider: Any, call: GraphifyCall) -> Optional[EvidenceItem]:
    """One Graphify MCP tool. Returns None on empty / error (still counts as a call)."""
    try:
        if call.tool == "get_node":
            node = provider.get_node(call.label)
            text = ""
            if node is not None:
                text = (getattr(node, "raw", {}) or {}).get("text") or ""
                if not text:
                    text = str(getattr(node, "label", "") or "")
            if not (text or "").strip():
                return None
            return EvidenceItem(
                id="",
                source="graphify",
                kind="node",
                path=call.path,
                symbol=call.symbol or call.label,
                text=str(text).strip()[:4000],
            )
        if call.tool == "get_neighbors":
            neigh = provider.get_neighbors(call.label)
            text = getattr(neigh, "raw_text", "") or ""
            if not str(text).strip():
                return None
            return EvidenceItem(
                id="",
                source="graphify",
                kind="neighbors",
                path=call.path,
                symbol=call.symbol or call.label,
                text=str(text).strip()[:4000],
            )
        if call.tool == "query":
            q = call.question or f"callers of {call.label}"
            result = provider.query(q, depth=3)
            text = getattr(result, "raw_text", "") or ""
            if not str(text).strip():
                return None
            return EvidenceItem(
                id="",
                source="graphify",
                kind="query",
                path=call.path,
                symbol=call.symbol or call.label,
                text=str(text).strip()[:4000],
            )
        if call.tool == "get_pr_impact" and call.pr_number is not None:
            impact = provider.get_pr_impact(call.pr_number, repo=call.repo)
            text = getattr(impact, "raw_text", "") or ""
            if not str(text).strip():
                return None
            return EvidenceItem(
                id="",
                source="graphify",
                kind="pr_impact",
                path=call.path,
                text=str(text).strip()[:4000],
            )
    except GraphifyMCPError:
        return None
    except Exception:
        return None
    return None


def _attach_evidence(finding: dict, items: List[EvidenceItem]) -> dict:
    if not items:
        return finding
    ids = list(finding.get("evidence_ids") or [])
    snippets = list(finding.get("investigation_snippets") or [])
    bits: List[str] = []
    for ev in items:
        if ev.id and ev.id not in ids:
            ids.append(ev.id)
        if ev.text:
            snippets.append(ev.text[:800])
            bits.append(f"[{ev.kind}] {ev.text[:600]}")
    finding["evidence_ids"] = ids
    finding["investigation_snippets"] = snippets[:6]
    if bits:
        extra = "\n\nGraphify investigation:\n" + "\n".join(bits[:4])
        finding["reasoning"] = (str(finding.get("reasoning") or "") + extra)[:4000]
    # Keep PR path as evidence universe — never replace with graph-only paths
    file_ = finding.get("file")
    ev_paths = list(finding.get("evidence") or [])
    if file_ and file_ not in ev_paths:
        ev_paths = [file_] + ev_paths
    finding["evidence"] = ev_paths
    return finding


def _pr_paths_in_blob(blob: str, files_changed: List[str]) -> List[str]:
    text = (blob or "").replace("\\", "/")
    hits: List[str] = []
    for p in files_changed or []:
        n = normalize_path(p)
        if not n or _is_trivial(n) or not _is_source_path(n):
            continue
        base = n.split("/")[-1]
        if n in text or (base and base in text):
            hits.append(n)
    return list(dict.fromkeys(hits))


def _collect_hypotheses(state: dict, files_changed: List[str], full_diff: str) -> List[Hypothesis]:
    facts = state.get("pr_facts") or {}
    if str(facts.get("classification") or "") == "lockfile-only":
        return []
    pool = list(state.get("hypothesis_pool") or [])
    if not pool:
        pool = list(state.get("validated_findings") or state.get("findings") or [])
    hyps = findings_to_hypotheses(
        pool, files_changed=files_changed, full_diff=full_diff, max_n=MAX_HYPOTHESES
    )
    # No kept finding with a real changed path → skip (don't Graphify for nothing)
    if not hyps:
        return []
    if len(hyps) < MAX_HYPOTHESES:
        plan = state.get("review_plan") or {}
        asks = plan.get("investigate") if isinstance(plan, dict) else None
        extra = asks_to_hypotheses(
            asks or [],
            files_changed=files_changed,
            full_diff=full_diff,
            start_index=len(hyps) + 1,
        )
        seen_files = {h.file for h in hyps}
        for h in extra:
            if h.file in seen_files:
                continue
            hyps.append(h)
            seen_files.add(h.file)
            if len(hyps) >= MAX_HYPOTHESES:
                break
    return hyps[:MAX_HYPOTHESES]


def run_investigation(state: dict, provider: Any) -> dict:
    """Testable core: provider is injected (real Graphify or fake)."""
    facts = state.get("pr_facts") or {}
    files_changed = list(
        facts.get("files_changed") or state.get("files_changed") or []
    )
    paths_in_diff = list(facts.get("paths_in_diff") or [])
    full_diff = state.get("full_diff") or ""
    repo = state.get("repo") or ""
    pr_number = state.get("number") or state.get("pr_number")

    hyps = _collect_hypotheses(state, files_changed, full_diff)
    if not hyps:
        return _skip("no_changed_path_hypotheses", state)

    asks = plan_typed_asks(hyps, pr_number=pr_number, repo=repo)
    deadline = time.monotonic() + TIMEOUT_S
    evidence: List[EvidenceItem] = []
    by_hyp: Dict[str, List[EvidenceItem]] = {h.id: [] for h in hyps}
    n_calls = 0
    n_hops = 0  # successful evidence-producing calls
    eid = 1
    op_log: List[dict] = []
    typed_hits: Dict[str, Dict[str, int]] = {
        h.id: {"callers": 0, "callees": 0, "tests": 0} for h in hyps
    }

    def _dispatch(ask: InvestigationAsk) -> List[EvidenceItem]:
        nonlocal n_calls, n_hops, eid
        if n_calls >= MAX_GRAPHIFY_CALLS_IN_INVESTIGATE:
            return []
        if time.monotonic() > deadline:
            print("[Investigate] timeout")
            return []
        op = ask.op or GraphOp.GET_NEIGHBORS
        path = ask.file or ""
        symbol = ask.symbol
        if path and not is_investigable_path(path, files_changed):
            if op == GraphOp.PR_IMPACT:
                path = ""
            elif symbol:
                path = ""
            else:
                return []
        if symbol:
            grounded = strip_ungrounded_symbol(symbol, files_changed, full_diff)
            if not grounded:
                symbol = None
                if op in (GraphOp.FIND_CALLERS, GraphOp.FIND_CALLEES, GraphOp.GET_NODE):
                    symbol = file_label(path) or None
                    if not symbol and op != GraphOp.GET_NEIGHBORS:
                        return []
        q = ask.question or ""
        if op in (GraphOp.FIND_CALLERS, GraphOp.FIND_CALLEES, GraphOp.FIND_TESTS) and q:
            if not question_grounded_in_pr(q, files_changed, full_diff):
                # Retarget the question at the grounded label
                lab = symbol or file_label(path)
                if not lab or not question_grounded_in_pr(
                    f"{op.value} {lab}", files_changed, full_diff
                ):
                    if op != GraphOp.GET_NODE:
                        return []
        n_calls += 1
        hid = ask.hypothesis_id or "-"
        print(
            f"[Investigate] {hid} ask={op.value} "
            f"symbol={symbol or ''} file={path}"
        )
        op_log.append({"hyp": hid, "op": op.value, "symbol": symbol or "", "file": path})
        items = run_op(
            provider,
            op,
            symbol=str(symbol or ""),
            path=path or None,
            pr_number=ask.pr_number if ask.pr_number is not None else pr_number,
            repo=ask.repo or repo,
        )
        if not items:
            return []
        n_hops += 1
        for it in items:
            it.id = _evidence_id(eid)
            eid += 1
            evidence.append(it)
            if hid in by_hyp:
                by_hyp[hid].append(it)
            else:
                for hyp in hyps:
                    by_hyp[hyp.id].append(it)
        return items

    impact_asks = [a for a in asks if a.op == GraphOp.PR_IMPACT]
    typed_asks = [a for a in asks if a.op != GraphOp.PR_IMPACT]
    by_ask_hyp: Dict[str, List[InvestigationAsk]] = {}
    for a in typed_asks:
        by_ask_hyp.setdefault(a.hypothesis_id or "", []).append(a)

    timed_out = False
    for h in hyps:
        if n_calls >= MAX_GRAPHIFY_CALLS_IN_INVESTIGATE or timed_out:
            break
        for ask in by_ask_hyp.get(h.id, []):
            if n_calls >= MAX_GRAPHIFY_CALLS_IN_INVESTIGATE:
                break
            if time.monotonic() > deadline:
                print("[Investigate] timeout")
                timed_out = True
                break
            items = _dispatch(ask)
            op = ask.op
            n = hit_count(items)
            if op == GraphOp.FIND_CALLERS:
                typed_hits[h.id]["callers"] = n
            elif op == GraphOp.FIND_CALLEES:
                typed_hits[h.id]["callees"] = n
            elif op == GraphOp.FIND_TESTS:
                typed_hits[h.id]["tests"] = n
        hits = typed_hits[h.id]
        if (
            hits["callers"] + hits["callees"] + hits["tests"] == 0
            and n_calls < MAX_GRAPHIFY_CALLS_IN_INVESTIGATE
            and not timed_out
        ):
            target = h.file or h.file_hint or ""
            lab = h.symbol or file_label(target)
            if lab and (not target or is_investigable_path(target, files_changed) or h.symbol):
                _dispatch(
                    InvestigationAsk(
                        op=GraphOp.GET_NEIGHBORS,
                        ask="get_neighbors",
                        file=target if is_investigable_path(target, files_changed) else "",
                        symbol=h.symbol or lab,
                        hypothesis_id=h.id,
                    )
                )
        print(
            f"[Investigate] {h.id} callers={hits['callers']} "
            f"callees={hits['callees']} tests={hits['tests']}"
        )

    if (
        impact_asks
        and n_calls < MAX_GRAPHIFY_CALLS_IN_INVESTIGATE
        and not timed_out
        and time.monotonic() <= deadline
    ):
        _dispatch(impact_asks[0])

    # Merge onto KEEP + PLAUSIBLE pool, then promote PLAUSIBLE when evidence names a PR path
    classified = [
        dict(f) if isinstance(f, dict) else f
        for f in (state.get("classified_findings") or [])
    ]
    kept = [dict(f) if isinstance(f, dict) else f for f in (state.get("validated_findings") or [])]
    if classified:
        kept = [f for f in classified if isinstance(f, dict)]
    for f in kept:
        if isinstance(f, dict) and f.get("symbol"):
            f["symbol"] = strip_ungrounded_symbol(
                f.get("symbol"), files_changed, full_diff
            )
    kept_by_id = {
        str(f.get("id") or ""): f
        for f in kept
        if isinstance(f, dict) and f.get("id")
    }
    kept_by_file: Dict[str, List[dict]] = {}
    for f in kept:
        if isinstance(f, dict) and f.get("file"):
            kept_by_file.setdefault(str(f["file"]), []).append(f)

    for h in hyps:
        items = by_hyp.get(h.id) or []
        h.evidence_ids = [e.id for e in items]
        if items:
            h.status = "confirmed"
        else:
            h.status = "uncertain"

        targets: List[dict] = []
        seen_t: set[int] = set()

        def _add_target(f: dict) -> None:
            i = id(f)
            if i in seen_t:
                return
            seen_t.add(i)
            targets.append(f)

        if h.finding_id and h.finding_id in kept_by_id:
            _add_target(kept_by_id[h.finding_id])
        for f in kept_by_file.get(h.file) or []:
            _add_target(f)
        if not targets and (h.symbol or h.file_hint):
            for f in kept:
                if not isinstance(f, dict):
                    continue
                if h.symbol and str(f.get("symbol") or "") == h.symbol:
                    _add_target(f)
                elif h.file_hint and str(f.get("file_hint") or "") == h.file_hint:
                    _add_target(f)
        for f in targets:
            _attach_evidence(f, items)
            f["investigation_status"] = h.status
            if h.question and not f.get("question"):
                f["question"] = h.question
            kind = str(f.get("hypothesis_status") or h.hypothesis_kind or KEEP)
            if kind == PLAUSIBLE:
                blob = " ".join(
                    [(e.path or "") + " " + (e.text or "") for e in items]
                )
                paths = _pr_paths_in_blob(blob, files_changed)
                if paths:
                    f["file"] = paths[0]
                    ev = list(f.get("evidence") or [])
                    if paths[0] not in ev:
                        ev = [paths[0]] + ev
                    f["evidence"] = ev
                    f["hypothesis_status"] = KEEP
                else:
                    f["hypothesis_status"] = UNRESOLVED

    keep_only = [
        f
        for f in kept
        if isinstance(f, dict) and str(f.get("hypothesis_status") or KEEP) == KEEP
    ]

    # Re-run the same 2.2 validator on KEEP (including promoted PLAUSIBLE)
    changed_symbols = extract_diff_symbols(full_diff)
    val = filter_findings(
        keep_only,
        files_changed=files_changed,
        paths_in_diff=paths_in_diff,
        changed_symbols=changed_symbols,
        full_diff=full_diff,
    )
    survivors = val["kept"]
    dropped = val["dropped"]
    for f in survivors:
        f["hypothesis_status"] = KEEP
    print(
        f"[Investigate] re-validate kept={len(survivors)} dropped={len(dropped)}"
    )
    print(
        f"[Investigate] hops={n_hops} calls={n_calls} hypotheses={len(hyps)}"
    )

    survivor_ids = {str(f.get("id") or "") for f in survivors}
    for h in hyps:
        if h.finding_id and h.finding_id not in survivor_ids:
            h.status = "rejected"

    for h in hyps:
        print(
            f"[Investigate] {h.id} status={h.status} file={h.file} "
            f"evidence={h.evidence_ids}"
        )

    report = {
        "ran": True,
        "skipped": False,
        "reason": "",
        "hops": n_hops,
        "calls": n_calls,
        "hypotheses": len(hyps),
        "statuses": {h.id: h.status for h in hyps},
        "asks": op_log,
        "typed_hits": typed_hits,
    }

    # Split survivors by category for display
    by_cat = {"correctness": [], "code_quality": [], "testing": []}
    for f in survivors:
        cat = str(f.get("category") or "")
        if cat in ("quality", "code_quality"):
            by_cat["code_quality"].append(f)
        elif cat in ("test", "testing"):
            by_cat["testing"].append(f)
        else:
            by_cat["correctness"].append(f)

    prev = state.get("validation_report") if isinstance(state.get("validation_report"), dict) else {}
    prev = dict(prev)
    prev["kept"] = len(survivors)
    prev["post_investigate_dropped"] = len(dropped)

    pool = [
        f
        for f in kept
        if isinstance(f, dict)
        and str(f.get("hypothesis_status") or KEEP) in (KEEP, PLAUSIBLE)
    ]
    return {
        "classified_findings": kept,
        "hypothesis_pool": pool,
        "validated_findings": survivors,
        "findings": survivors,
        "hypotheses": [h.model_dump() for h in hyps],
        "investigation_evidence": [e.model_dump() for e in evidence],
        "investigation_report": report,
        "validation_report": prev,
        "correctness_findings": by_cat["correctness"],
        "quality_findings": by_cat["code_quality"],
        "testing_findings": by_cat["testing"],
        "traces": [
            {
                "agent": "Investigate",
                "output": (
                    f"hops={n_hops} calls={n_calls} hypotheses={len(hyps)} "
                    f"kept={len(survivors)}"
                ),
            }
        ],
    }


def investigate_node(state: dict) -> dict:
    """LangGraph node: after classify_hypotheses, before validate_findings."""
    repo = state.get("repo") or ""
    try:
        from core.graphify_retriever import GraphifyRetriever
        from core.repository_knowledge.structural import graph_available

        if not repo or not graph_available(repo):
            return _skip("graphify_missing", state)
        retriever = GraphifyRetriever(repo)
        provider = retriever.provider
    except FileNotFoundError:
        return _skip("graphify_missing", state)
    except Exception as exc:
        return _skip(f"graphify_unavailable:{type(exc).__name__}", state)

    return run_investigation(state, provider)
