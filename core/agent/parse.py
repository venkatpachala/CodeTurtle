"""Parse BundleAgent LLM output: JSON candidate list, tool call, or invalid."""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Tuple

from core.agent.contract import classify_kind

_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.S | re.I)


def _load_json(blob: str) -> Any:
    return json.loads(blob)


def _extract_json_blob(text: str) -> str | None:
    raw = (text or "").strip()
    if not raw:
        return None
    for m in _FENCE_RE.finditer(raw):
        inner = (m.group(1) or "").strip()
        if inner:
            return inner
    for opener, closer in (("[", "]"), ("{", "}")):
        start = raw.find(opener)
        end = raw.rfind(closer)
        if start >= 0 and end > start:
            return raw[start : end + 1]
    return None


def parse_agent_output(text: str) -> Tuple[str, Any]:
    """Return ('candidates', list) | ('tool', dict) | ('invalid', None)."""
    blob = _extract_json_blob(text)
    if blob is None:
        return "invalid", None
    try:
        data = _load_json(blob)
    except (json.JSONDecodeError, TypeError, ValueError):
        return "invalid", None
    if isinstance(data, list):
        return "candidates", data
    if isinstance(data, dict):
        if data.get("tool"):
            return "tool", data
        if "candidates" in data and isinstance(data.get("candidates"), list):
            return "candidates", data.get("candidates") or []
    return "invalid", None


def candidate_dict(raw: Any, *, bundle_id: str) -> Dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    file = str(raw.get("file") or raw.get("path") or "").replace("\\", "/").strip()
    if not file:
        return None
    source = str(raw.get("source") or "agent").strip().lower()
    if source not in ("agent", "rule"):
        source = "agent"
    try:
        start_line = int(raw.get("start_line") or 0)
    except (TypeError, ValueError):
        start_line = 0
    evidence = raw.get("evidence_paths") or raw.get("evidence") or []
    if isinstance(evidence, str):
        evidence = [evidence]
    paths = [str(p).replace("\\", "/") for p in evidence if p]
    title = str(raw.get("title") or raw.get("claim") or "").strip()
    claim = str(raw.get("claim") or raw.get("title") or "").strip()
    kind = classify_kind(title, claim, str(raw.get("kind") or "") or None)
    path_syms = raw.get("execution_path") or []
    if isinstance(path_syms, str):
        path_syms = [s.strip() for s in path_syms.split(",") if s.strip()]
    evidence = raw.get("evidence") or paths
    if isinstance(evidence, str):
        evidence = [evidence]
    try:
        confidence = float(raw.get("confidence") if raw.get("confidence") is not None else 0.5)
    except (TypeError, ValueError):
        confidence = 0.5
    return {
        "bundle_id": str(raw.get("bundle_id") or bundle_id),
        "file": file,
        "symbol": str(raw.get("symbol") or ""),
        "start_line": start_line,
        "title": title,
        "claim": claim,
        "existing_code": str(raw.get("existing_code") or "").strip(),
        "invariant": str(raw.get("invariant") or "").strip(),
        "violating_condition": str(raw.get("violating_condition") or "").strip(),
        "expected": str(raw.get("expected") or "").strip(),
        "actual": str(raw.get("actual") or "").strip(),
        "execution_path": [str(s).strip() for s in path_syms if s],
        "evidence": [str(p).replace("\\", "/") for p in evidence if p],
        "counter_evidence": [],
        "verify_status": str(raw.get("verify_status") or "candidate"),
        "severity": str(raw.get("severity") or "medium"),
        "confidence": confidence,
        "source": source,
        "evidence_paths": paths or [str(p).replace("\\", "/") for p in evidence if p],
        "kind": kind,
    }
