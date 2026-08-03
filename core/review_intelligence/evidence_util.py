from __future__ import annotations

import re
from typing import Any, Iterable, List, Set


def paths_from_context(context_from_kb: str) -> Set[str]:
    """Parse paths from formatted evidence blocks like: [1] path=graphify/build.py"""
    if not context_from_kb:
        return set()
    found = set(re.findall(r"path=([^\s\n]+)", context_from_kb))
    found |= set(re.findall(r"`([a-zA-Z0-9_./\\-]+\.(?:py|ts|js|go|rs|md))`", context_from_kb))
    return {p.strip().strip("`") for p in found if p}


def normalize_evidence(refs: Iterable[str], allowed: Set[str]) -> List[str]:
    out: List[str] = []
    for r in refs or []:
        s = str(r).strip()
        if not s:
            continue
        # accept path or path:lines
        base = s.split(":")[0].strip()
        if allowed and base not in allowed and s not in allowed:
            # still keep if it looks like a path under repo
            if "/" not in s and "\\" not in s:
                continue
        out.append(s)
    return list(dict.fromkeys(out))


def finding_to_dict(f: Any) -> dict:
    if hasattr(f, "model_dump"):
        return f.model_dump()
    if isinstance(f, dict):
        return f
    return {"title": str(f), "evidence": [], "severity": "low", "confidence": 0.0}