"""Trace-based golden issue survival diagnostics."""
from __future__ import annotations
from typing import Any, Dict, List

def survival_analysis(goldens: List[Any], trace: List[Dict[str, Any]], findings: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Report the last observed pipeline stage for each golden issue.

    Exact semantic attribution is intentionally conservative: it uses matching
    path/title tokens and otherwise reports that no candidate was observed.
    """
    out=[]
    for raw in goldens:
        g=raw if isinstance(raw,dict) else vars(raw); text=str(g.get("comment") or "").lower(); path=str(g.get("path") or "")
        relevant=[e for e in trace if (not path or e.get("file")==path) and (not text or any(w in str(e.get("title") or "").lower() for w in text.split() if len(w)>4))]
        final=any((not path or f.get("file")==path) for f in findings)
        out.append({"golden":g,"survived_to_final":final,"last_event":relevant[-1] if relevant else None,"lost_at":None if final else (relevant[-1].get("stage") if relevant else "candidate_generation")})
    return {"golden_issues":out,"count":len(out)}
