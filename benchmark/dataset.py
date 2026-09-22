"""benchmark/dataset.py — Read-only loader for the official benchmark dataset.

INVARIANT: This module NEVER writes to benchmark_data.json.
All mutations (injecting reviews) are forbidden here.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass
class GoldenComment:
    comment: str = ""
    severity: str = ""
    category: str = ""

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "GoldenComment":
        return cls(
            comment=str(d.get("comment") or ""),
            severity=str(d.get("severity") or ""),
            category=str(d.get("category") or ""),
        )


@dataclass
class BenchmarkPR:
    pr_url: str
    title: str = ""
    source_repo: str = ""
    golden_comments: List[GoldenComment] = field(default_factory=list)
    original_url: str = ""

    @property
    def repo(self) -> str:
        """Extract owner/repo from pr_url."""
        # https://github.com/owner/repo/pull/123
        parts = self.pr_url.rstrip("/").split("/")
        if len(parts) >= 5:
            return f"{parts[-4]}/{parts[-3]}"
        return self.source_repo or ""

    @property
    def number(self) -> int:
        """Extract PR number from pr_url."""
        parts = self.pr_url.rstrip("/").split("/")
        try:
            return int(parts[-1])
        except (ValueError, IndexError):
            return 0


@dataclass
class BenchmarkDataset:
    prs: List[BenchmarkPR] = field(default_factory=list)
    raw_path: Path = field(default_factory=Path)

    def __len__(self) -> int:
        return len(self.prs)

    def __iter__(self):
        return iter(self.prs)

    def __getitem__(self, idx):
        return self.prs[idx]


def load_dataset(
    path: str = "",
    *,
    max_prs: Optional[int] = None,
    start: int = 0,
) -> BenchmarkDataset:
    """Load benchmark_data.json as a read-only dataset.

    Args:
        path: Path to benchmark_data.json. Defaults to the standard location.
        max_prs: Optional limit on number of PRs to load.
        start: 0-indexed start offset.

    Returns:
        BenchmarkDataset (immutable view over the JSON).

    Raises:
        FileNotFoundError: if the file does not exist.
    """
    if not path:
        # Try standard location relative to common project layouts
        candidates = [
            Path("D:/code-review-benchmark/code-review-benchmark/offline/results/benchmark_data.json"),
            Path("benchmark_data.json"),
            Path("results/benchmark_data.json"),
        ]
        for c in candidates:
            if c.is_file():
                path = str(c)
                break
        if not path:
            raise FileNotFoundError(
                "benchmark_data.json not found. Pass an explicit path or set BENCHMARK_DATA_PATH."
            )

    bm_path = Path(path).resolve()
    if not bm_path.is_file():
        raise FileNotFoundError(f"benchmark_data.json not found at {bm_path}")

    with open(bm_path, "r", encoding="utf-8") as f:
        raw = json.load(f)

    prs: List[BenchmarkPR] = []
    for pr_url, entry in raw.items():
        if not isinstance(entry, dict):
            continue
        golden_raw = entry.get("golden_comments") or []
        golden = [GoldenComment.from_dict(gc) for gc in golden_raw if isinstance(gc, dict)]
        prs.append(
            BenchmarkPR(
                pr_url=str(pr_url),
                title=str(entry.get("pr_title") or ""),
                source_repo=str(entry.get("source_repo") or ""),
                golden_comments=golden,
                original_url=str(entry.get("original_url") or pr_url),
            )
        )

    # Sort for deterministic ordering
    prs.sort(key=lambda p: p.pr_url)

    # Apply slicing
    prs = prs[start:]
    if max_prs is not None:
        prs = prs[:max_prs]

    return BenchmarkDataset(prs=prs, raw_path=bm_path)
