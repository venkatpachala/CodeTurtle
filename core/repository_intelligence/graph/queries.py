"""Graph queries for retrieval / evidence expansion."""
from __future__ import annotations
from typing import List
from core.repository_intelligence.graph.store import GraphStore


class GraphQueries:
    def __init__(self, store: GraphStore | None = None):
        self.store = store or GraphStore()

    def direct_imports(self, path: str, limit: int = 20) -> List[str]:
        """Files that `path` imports."""
        q = """
        MATCH (f:File {path: $path})-[:IMPORTS]->(dep:File)
        RETURN dep.path AS path
        LIMIT $limit
        """
        return self._paths(q, path=path, limit=limit)

    def importers(self, path: str, limit: int = 20) -> List[str]:
        """Files that import `path` (blast radius)."""
        q = """
        MATCH (f:File)-[:IMPORTS]->(dep:File {path: $path})
        RETURN f.path AS path
        LIMIT $limit
        """
        return self._paths(q, path=path, limit=limit)

    def expand_paths(self, paths: List[str], limit_per: int = 10) -> List[str]:
        """
        For each changed/retrieved path, add:
          - direct imports
          - reverse importers
        Deduped, original paths first.
        """
        seen = set()
        ordered: List[str] = []

        def add(p: str):
            p = p.replace("\\", "/")
            if p not in seen:
                seen.add(p)
                ordered.append(p)

        for p in paths:
            add(p)

        for p in list(paths):
            for dep in self.direct_imports(p, limit=limit_per):
                add(dep)
            for src in self.importers(p, limit=limit_per):
                add(src)

        return ordered

    def _paths(self, query: str, **params) -> List[str]:
        driver = self.store.connect()
        try:
            with driver.session() as session:
                return [r["path"] for r in session.run(query, **params)]
        except Exception as e:
            print(f"[GraphQueries] {e}")
            return []