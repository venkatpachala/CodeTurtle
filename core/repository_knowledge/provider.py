from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List, Optional

from core.repository_knowledge.models import (
    GraphNode,
    GraphStats,
    KnowledgeQueryResult,
    NeighborResult,
    PathResult,
    PRImpact,
)


class RepositoryKnowledgeProvider(ABC):
    """Structural repository truth. CodeTurtle never talks to Graphify internals."""

    @abstractmethod
    def healthcheck(self) -> str:
        """Return a short status string or raise."""

    @abstractmethod
    def query(self, question: str, depth: int = 3) -> KnowledgeQueryResult:
        ...

    @abstractmethod
    def get_node(self, label: str) -> Optional[GraphNode]:
        ...

    @abstractmethod
    def get_neighbors(
        self,
        label: str,
        relation_filter: Optional[str] = None,
    ) -> NeighborResult:
        ...

    @abstractmethod
    def shortest_path(self, source: str, target: str, max_hops: int = 8) -> PathResult:
        ...

    @abstractmethod
    def graph_stats(self) -> GraphStats:
        ...

    @abstractmethod
    def get_pr_impact(self, pr_number: int, repo: Optional[str] = None) -> PRImpact:
        ...

    def find_symbol(self, name: str, path: Optional[str] = None) -> Optional[GraphNode]:
        return self.get_node(name)

    def find_callers(self, symbol: str) -> NeighborResult:
        return self.get_neighbors(symbol, relation_filter="call")

    def find_callees(self, symbol: str) -> NeighborResult:
        return self.get_neighbors(symbol, relation_filter="call")

    def find_impact(self, target: str) -> KnowledgeQueryResult:
        return self.query(f"what is impacted if {target} changes?", depth=3)

    def list_tools(self) -> List[str]:
        return []

    def investigate_file(self, path: str, symbol: Optional[str] = None) -> List[dict]:
        """Phase 3 helper: get_node + get_neighbors for a changed file. Two Graphify calls."""
        label = (symbol or "").strip() or (path or "").replace("\\", "/").split("/")[-1]
        items: List[dict] = []
        try:
            node = self.get_node(label)
            text = ""
            if node is not None:
                text = (node.raw or {}).get("text") or node.label or ""
            if str(text).strip():
                items.append(
                    {
                        "source": "graphify",
                        "kind": "node",
                        "path": path,
                        "symbol": symbol or label,
                        "text": str(text).strip()[:4000],
                    }
                )
        except Exception:
            pass
        try:
            neigh = self.get_neighbors(label)
            text = getattr(neigh, "raw_text", "") or ""
            if str(text).strip():
                items.append(
                    {
                        "source": "graphify",
                        "kind": "neighbors",
                        "path": path,
                        "symbol": symbol or label,
                        "text": str(text).strip()[:4000],
                    }
                )
        except Exception:
            pass
        return items