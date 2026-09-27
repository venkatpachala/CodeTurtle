"""Explicit, disjoint PR selection without exposing gold labels to prediction runs."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

SplitName = Literal["development", "validation", "test"]


@dataclass(frozen=True)
class DatasetSplit:
    name: str
    split: SplitName
    prs: tuple[str, ...]
    used_for_system_design: bool
    eligible_for_headline_metrics: bool
    path: Path


def load_split(path: str | Path) -> DatasetSplit:
    source = Path(path).resolve()
    raw = json.loads(source.read_text(encoding="utf-8"))
    split = raw.get("split")
    if split not in {"development", "validation", "test"}:
        raise ValueError(f"Invalid dataset split: {split!r}")
    prs = tuple(str(url).rstrip("/") for url in raw.get("prs", []))
    if not prs or len(prs) != len(set(prs)):
        raise ValueError("Split must contain nonempty, unique PR URLs")
    if any(not url.startswith("https://github.com/") or "/pull/" not in url for url in prs):
        raise ValueError("Split contains a malformed GitHub PR URL")
    if split == "development" and raw.get("eligible_for_headline_metrics") is not False:
        raise ValueError("Development PRs cannot be headline eligible")
    return DatasetSplit(
        name=str(raw.get("name") or source.stem),
        split=split,
        prs=prs,
        used_for_system_design=bool(raw.get("used_for_system_design", False)),
        eligible_for_headline_metrics=bool(raw.get("eligible_for_headline_metrics", False)),
        path=source,
    )


def assert_disjoint(*splits: DatasetSplit) -> None:
    owner: dict[str, str] = {}
    for split in splits:
        for url in split.prs:
            if url in owner:
                raise ValueError(f"PR appears in both {owner[url]} and {split.name}: {url}")
            owner[url] = split.name


def load_registered_splits(root: Path) -> list[DatasetSplit]:
    paths = sorted(root.glob("*/*.json"))
    splits = [load_split(path) for path in paths]
    assert_disjoint(*splits)
    return splits
