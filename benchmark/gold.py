"""Gold-label adjudication sidecars; the upstream benchmark file stays immutable."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

GoldStatus = Literal["confirmed", "ambiguous", "rejected", "adjudication_required"]
VALID_STATUSES = {"confirmed", "ambiguous", "rejected", "adjudication_required"}


@dataclass(frozen=True)
class GoldAdjudication:
    gold_id: str
    status: GoldStatus
    reason: str
    evidence: str = ""


def load_adjudications(path: str | Path) -> dict[str, dict[str, GoldAdjudication]]:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    result: dict[str, dict[str, GoldAdjudication]] = {}
    for pr_url, items in (raw.get("prs") or {}).items():
        if not isinstance(items, list):
            raise ValueError(f"Adjudications for {pr_url} must be a list")
        by_id: dict[str, GoldAdjudication] = {}
        for item in items:
            gold_id = str(item.get("gold_id") or "")
            status = str(item.get("status") or "")
            reason = str(item.get("reason") or "").strip()
            evidence = str(item.get("evidence") or "").strip()
            if not gold_id or status not in VALID_STATUSES or not reason or (
                status in {"confirmed", "rejected"} and not evidence
            ):
                raise ValueError(f"Invalid gold adjudication for {pr_url}: {item}")
            if gold_id in by_id:
                raise ValueError(f"Duplicate gold ID {gold_id} for {pr_url}")
            by_id[gold_id] = GoldAdjudication(gold_id, status, reason, evidence)  # type: ignore[arg-type]
        result[pr_url.rstrip("/")] = by_id
    return result


def statuses_for_pr(
    pr_url: str, goldens: list[Any], adjudications: dict[str, dict[str, GoldAdjudication]],
) -> list[GoldAdjudication]:
    by_id = adjudications.get(pr_url.rstrip("/"), {})
    expected = {f"G-{index:03d}" for index in range(1, len(goldens) + 1)}
    unknown = set(by_id) - expected
    if unknown:
        raise ValueError(f"Unknown gold IDs for {pr_url}: {sorted(unknown)}")
    return [
        by_id.get(gold_id) or GoldAdjudication(
            gold_id, "adjudication_required", "No adjudication recorded for this source label"
        )
        for gold_id in (f"G-{index:03d}" for index in range(1, len(goldens) + 1))
    ]
