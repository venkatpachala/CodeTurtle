"""Graph queries for retrieval / evidence expansion."""
from __future__ import annotations
from typing import List
from core.repository_intelligence.graph.store import GraphStore


# core/repository_intelligence/graph/queries.py

class GraphQueries:
    def __init__(self, store=None):
        from core.repository_intelligence.graph.store import GraphStore
        self.store = store or GraphStore()

    def expand_imports(self, paths: list[str], limit: int = 15) -> list[str]:
        paths = [p.replace("\\", "/") for p in paths]
        driver = self.store.connect()
        out = []
        with driver.session() as session:
            result = session.run(
                """
                MATCH (f:File)-[:IMPORTS]->(g:File)
                WHERE f.path IN $paths
                RETURN DISTINCT g.path AS path
                LIMIT $limit
                UNION
                MATCH (f:File)<-[:IMPORTS]-(g:File)
                WHERE f.path IN $paths
                RETURN DISTINCT g.path AS path
                LIMIT $limit
                """,
                paths=paths,
                limit=limit,
            )
            out = [r["path"] for r in result if r["path"]]
        return out[:limit]

    def expand_calls(
        self,
        paths: list[str],
        limit: int = 10,
        exclude_prefixes: tuple = ("tests/", "worked/"),
        max_callee_degree: int = 150,
    ) -> list[str]:
        """Map changed files → symbols → CALLS → related file paths."""
        paths = [p.replace("\\", "/") for p in paths]
        driver = self.store.connect()
        with driver.session() as session:
            result = session.run(
                """
                MATCH (f:File)-[:CONTAINS]->(s:Symbol)-[:CALLS]->(t:Symbol)
                WHERE f.path IN $paths
                WITH t, count(*) AS dummy
                MATCH (t)<-[:CALLS]-(:Symbol)
                WITH t, count(*) AS degree
                WHERE degree <= $max_degree
                MATCH (tf:File)-[:CONTAINS]->(t)
                WHERE none(prefix IN $exclude WHERE tf.path STARTS WITH prefix)
                RETURN DISTINCT tf.path AS path
                LIMIT $limit
                """,
                paths=paths,
                max_degree=max_callee_degree,
                exclude=list(exclude_prefixes),
                limit=limit,
            )
            return [r["path"] for r in result if r["path"]]