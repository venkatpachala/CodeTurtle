"""Audited, issue-specific failure attribution after predictions are sealed."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from benchmark.issue_trace import FailureStage


def load_failure_adjudications(path: str | Path) -> dict[tuple[str, str], dict[str, Any]]:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    result: dict[tuple[str, str], dict[str, Any]] = {}
    valid = {stage.value for stage in FailureStage}
    for pr_url, entries in (raw.get("prs") or {}).items():
        for item in entries:
            gold_id = str(item.get("gold_id") or "")
            stage = str(item.get("failure_stage") or "")
            evidence = str(item.get("evidence") or "").strip()
            rationale = str(item.get("rationale") or "").strip()
            if not gold_id or stage not in valid or not evidence or not rationale:
                raise ValueError(f"Invalid failure adjudication for {pr_url}: {item}")
            key = (pr_url.rstrip("/"), gold_id)
            if key in result:
                raise ValueError(f"Duplicate failure adjudication: {key}")
            result[key] = {"failure_stage": stage, "evidence": evidence, "rationale": rationale}
    return result
