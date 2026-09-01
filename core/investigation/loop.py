"""Bounded investigation: Graphify hops on real changed files, then re-validate."""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from core.finding_validator import filter_findings
from core.investigation.models import EvidenceItem, GraphifyCall, Hypothesis
from core.investigation.planner import (
    MAX_GRAPHIFY_CALLS_IN_INVESTIGATE,
    MAX_HYPOTHESES,
    TIMEOUT_S,
    asks_to_hypotheses,
    findings_to_hypotheses,
    is_investigable_path,
    plan_graphify_calls,
    strip_ungrounded_symbol,
)
from core.pr_facts import extract_diff_symbols, question_grounded_in_pr
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


def _collect_hypotheses(state: dict, files_changed: List[str], full_diff: str) -> List[Hypothesis]:
    kept = list(state.get("validated_findings") or state.get("findings") or [])
    hyps = findings_to_hypotheses(
        kept, files_changed=files_changed, full_diff=full_diff, max_n=MAX_HYPOTHESES
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

    calls = plan_graphify_calls(hyps, pr_number=pr_number, repo=repo)
    deadline = time.monotonic() + TIMEOUT_S
    evidence: List[EvidenceItem] = []
    by_hyp: Dict[str, List[EvidenceItem]] = {h.id: [] for h in hyps}
    n_calls = 0
    n_hops = 0  # successful evidence-producing calls
    eid = 1

    for call in calls:
        if n_calls >= MAX_GRAPHIFY_CALLS_IN_INVESTIGATE:
            break
        if time.monotonic() > deadline:
            print("[Investigate] timeout")
            break
        # Never hop on a path that is not in the PR
        if call.path and not is_investigable_path(call.path, files_changed):
            if call.tool != "get_pr_impact":
                continue
        if call.symbol:
            if not strip_ungrounded_symbol(call.symbol, files_changed, full_diff):
                call.symbol = None
        if call.tool == "query" and call.question:
            if not question_grounded_in_pr(call.question, files_changed, full_diff):
                continue

        n_calls += 1
        print(
            f"[Investigate] {call.hypothesis_id or '-'} "
            f"file={call.path} call={call.tool} label={call.label}"
        )
        item = execute_call(provider, call)
        if item is None:
            continue
        item.id = _evidence_id(eid)
        eid += 1
        n_hops += 1
        evidence.append(item)
        hid = call.hypothesis_id
        if hid and hid in by_hyp:
            by_hyp[hid].append(item)
        else:
            for h in hyps:
                by_hyp[h.id].append(item)

    # Merge onto findings + set hypothesis status
    kept = [dict(f) if isinstance(f, dict) else f for f in (state.get("validated_findings") or [])]
    for f in kept:
        if isinstance(f, dict) and f.get("symbol"):
            f["symbol"] = strip_ungrounded_symbol(
                f.get("symbol"), files_changed, full_diff
            )
    kept_by_id = {str(f.get("id") or ""): f for f in kept if isinstance(f, dict)}
    kept_by_file = {}
    for f in kept:
        if isinstance(f, dict) and f.get("file"):
            kept_by_file.setdefault(f["file"], []).append(f)

    for h in hyps:
        items = by_hyp.get(h.id) or []
        h.evidence_ids = [e.id for e in items]
        if items:
            h.status = "confirmed"
        else:
            h.status = "uncertain"

        targets: List[dict] = []
        if h.finding_id and h.finding_id in kept_by_id:
            targets.append(kept_by_id[h.finding_id])
        else:
            targets.extend(kept_by_file.get(h.file) or [])
        for f in targets:
            _attach_evidence(f, items)
            f["investigation_status"] = h.status
            if h.question and not f.get("question"):
                f["question"] = h.question

    # Re-run the same 2.2 validator
    changed_symbols = extract_diff_symbols(full_diff)
    val = filter_findings(
        kept,
        files_changed=files_changed,
        paths_in_diff=paths_in_diff,
        changed_symbols=changed_symbols,
        full_diff=full_diff,
    )
    survivors = val["kept"]
    dropped = val["dropped"]
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

    return {
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
    """LangGraph node: after validate_findings, before critic."""
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
