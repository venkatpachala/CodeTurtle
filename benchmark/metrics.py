"""Aggregate benchmark metrics and latency percentiles."""
from __future__ import annotations
from typing import Any, Dict, Iterable, List

ACTIONABLE_CATEGORIES = {"api", "bug", "concurrency", "correctness", "data", "perf", "performance", "security"}
BLOCKING_SEVERITIES = {"critical", "high"}
REQUEST_CHANGES_SEVERITIES = {"medium", "concern", "high", "critical", "blocking"}

def _ratio(n: int, d: int) -> float: return round(n / d, 4) if d else 0.0
def _pct(values: List[float], q: float) -> float:
    if not values: return 0.0
    values = sorted(values); return round(values[min(len(values)-1, int((len(values)-1)*q))], 3)

def aggregate_metrics(evaluations: Iterable[Dict[str, Any]], predictions: Iterable[Dict[str, Any]] = ()) -> Dict[str, Any]:
    evs = list(evaluations); preds = list(predictions); tp=sum(x.get("tp",0) for x in evs); fp=sum(x.get("fp",0) for x in evs); fn=sum(x.get("fn",0) for x in evs)
    precision=_ratio(tp,tp+fp); recall=_ratio(tp,tp+fn)
    lat=[]
    healthy_runs = total_runs = 0
    for p in preds:
        t=p.get("telemetry") or {}; value=t.get("latency_seconds") or (t.get("timing") or {}).get("total_s")
        if value is not None: lat.append(float(value))
        for run in t.get("agent_runs") or p.get("agent_runs") or []:
            if not isinstance(run, dict): continue
            total_runs += 1
            if str(run.get("status") or "") in {"VALID_CANDIDATES", "VALID_EMPTY", "LEGACY"}: healthy_runs += 1
    breakdown = {"category": {}, "severity": {}}
    for ev in evs:
        for match in ev.get("matches", []):
            golden = match.get("golden") or {}; predicted = match.get("prediction") or {}
            for field, bucket in (("category", "category"), ("severity", "severity")):
                key = str(golden.get(field) or predicted.get(field) or "unknown").lower()
                row = breakdown[bucket].setdefault(key, {"tp": 0, "fp": 0, "fn": 0})
                row["tp"] += 1
        for miss in ev.get("false_negatives", []):
            golden = miss.get("golden") or {}
            for field, bucket in (("category", "category"), ("severity", "severity")):
                key = str(golden.get(field) or "unknown").lower(); breakdown[bucket].setdefault(key, {"tp":0,"fp":0,"fn":0})["fn"] += 1
        for noise in ev.get("false_positives", []):
            finding = noise.get("finding") or {}
            for field, bucket in (("category", "category"), ("severity", "severity")):
                key = str(finding.get(field) or "unknown").lower(); breakdown[bucket].setdefault(key, {"tp":0,"fp":0,"fn":0})["fp"] += 1
    for groups in breakdown.values():
        for row in groups.values():
            row["precision"] = _ratio(row["tp"], row["tp"] + row["fp"])
            row["recall"] = _ratio(row["tp"], row["tp"] + row["fn"])
            row["f1"] = round(2 * row["precision"] * row["recall"] / (row["precision"] + row["recall"]), 4) if row["precision"] + row["recall"] else 0.0
    actionable_tp = actionable_fn = actionable_fp = 0
    blocking_tp = blocking_fn = 0
    clean_prs = clean_prs_with_fp = 0
    for ev in evs:
        golden_total = len(ev.get("matches") or []) + len(ev.get("false_negatives") or [])
        if golden_total == 0:
            clean_prs += 1
            if ev.get("false_positives"): clean_prs_with_fp += 1
        actionable_fp += len(ev.get("false_positives") or [])
        for match in ev.get("matches") or []:
            golden = match.get("golden") or {}
            category = str(golden.get("category") or "").lower()
            severity = str(golden.get("severity") or "").lower()
            if category in ACTIONABLE_CATEGORIES:
                actionable_tp += 1
                if severity in BLOCKING_SEVERITIES: blocking_tp += 1
            else:
                actionable_fp += 1
        for miss in ev.get("false_negatives") or []:
            golden = miss.get("golden") or {}
            category = str(golden.get("category") or "").lower()
            severity = str(golden.get("severity") or "").lower()
            if category in ACTIONABLE_CATEGORIES:
                actionable_fn += 1
                if severity in BLOCKING_SEVERITIES: blocking_fn += 1
    decision_total = decision_correct = over_blocking = under_blocking = 0
    decision_confusion: Dict[str, Dict[str, int]] = {}
    rank = {"MERGE": 0, "COMMENT": 1, "REQUEST_CHANGES": 2}
    for ev, pred in zip(evs, preds):
        goldens = [m.get("golden") or {} for m in ev.get("matches") or []]
        goldens += [m.get("golden") or {} for m in ev.get("false_negatives") or []]
        # Keep benchmark decision expectations aligned with the product policy:
        # a verified medium-or-higher defect requests changes; low issues comment.
        if any(str(g.get("severity") or "").lower() in REQUEST_CHANGES_SEVERITIES for g in goldens):
            expected = "REQUEST_CHANGES"
        elif goldens:
            expected = "COMMENT"
        else:
            expected = "MERGE"
        actual = str(pred.get("decision") or pred.get("recommendation") or "COMMENT").upper()
        if actual not in rank: actual = "COMMENT"
        decision_total += 1
        decision_correct += int(actual == expected)
        over_blocking += int(rank[actual] > rank[expected])
        under_blocking += int(rank[actual] < rank[expected])
        decision_confusion.setdefault(expected, {}).setdefault(actual, 0)
        decision_confusion[expected][actual] += 1
    ap = _ratio(actionable_tp, actionable_tp + actionable_fp)
    ar = _ratio(actionable_tp, actionable_tp + actionable_fn)
    actionable = {
        "tp": actionable_tp, "fp": actionable_fp, "fn": actionable_fn,
        "precision": ap, "recall": ar,
        "f1": round(2 * ap * ar / (ap + ar), 4) if ap + ar else 0.0,
        "blocking_recall": _ratio(blocking_tp, blocking_tp + blocking_fn),
        "clean_pr_false_positive_rate": _ratio(clean_prs_with_fp, clean_prs),
    }
    return {"prs": len(evs), "tp":tp,"fp":fp,"fn":fn,"precision":precision,"recall":recall,"f1":round(2*precision*recall/(precision+recall),4) if precision+recall else 0.0,"pr_detection_rate":_ratio(sum(1 for x in evs if x.get("tp",0)),len(evs)),"fp_per_pr":_ratio(fp,len(evs)),"actionable":actionable,"agent_run_success_rate":_ratio(healthy_runs,total_runs),"decision":{"accuracy":_ratio(decision_correct,decision_total),"over_blocking_rate":_ratio(over_blocking,decision_total),"under_blocking_rate":_ratio(under_blocking,decision_total),"confusion":decision_confusion},"breakdowns":breakdown,"latency_seconds":{"p50":_pct(lat,.5),"p90":_pct(lat,.9),"p95":_pct(lat,.95),"p99":_pct(lat,.99)}}
