"""benchmark/models.py - Benchmark data schema for Code Review Benchmark."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, List, Optional


@dataclass
class BenchmarkFinding:
    path: str
    line: Optional[int]
    body: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class BenchmarkReview:
    tool: str = "codeturtle"
    pr_url: str = ""
    repo_name: Optional[str] = None
    model: Optional[str] = None
    review_comments: List[BenchmarkFinding] = field(default_factory=list)
    latency_seconds: Optional[float] = None
    decision: Optional[str] = None
    policy_reason: Optional[str] = None
    coverage_total: Optional[int] = None
    coverage_packed: Optional[int] = None
    coverage_ratio: Optional[float] = None
    created_at: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["review_comments"] = [
            finding.to_dict() if hasattr(finding, "to_dict") else finding
            for finding in (self.review_comments or [])
        ]
        return data

    def to_benchmark_data_review(self) -> dict[str, Any]:
        """Format matching benchmark_data.json 'reviews' element."""
        from datetime import datetime, timezone

        return {
            "tool": self.tool,
            "pr_url": self.pr_url,
            "review_comments": [
                {
                    "path": f.path,
                    "line": f.line,
                    "body": f.body,
                    "created_at": self.created_at or datetime.now(timezone.utc).isoformat(),
                }
                for f in (self.review_comments or [])
            ],
        }
