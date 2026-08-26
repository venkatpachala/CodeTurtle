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