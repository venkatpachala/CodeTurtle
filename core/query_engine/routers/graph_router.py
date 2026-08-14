"""Read-only Neo4j access for IMPORTS and CALLS via GraphStore.driver."""

from __future__ import annotations

from typing import Any, List, Optional

from core.query_engine.errors import GraphUnavailableError
from core.query_engine.types import CallEdge, DependencyEdge, normalize_path


class GraphRouter:
    def __init__(self, repo_name: str, graph_store=None):
        self.repo_name = repo_name
        self._store = graph_store
        self._driver = None
        self._available = False
        self._connect_error = ""
        self._connect()

    @property
    def available(self) -> bool:
        return self._available

    def _connect(self) -> None:
        self._available = False
        self._driver = None
        self._connect_error = ""

        # 1) Project GraphStore
        try:
            if self._store is None:
                from core.repository_intelligence.graph.store import GraphStore

                self._store = GraphStore()

            # connect() establishes driver
            if hasattr(self._store, "connect"):
                self._store.connect()

            # health_check (not health)
            if hasattr(self._store, "health_check"):
                ok = self._store.health_check()
                if ok is False:
                    self._connect_error = "GraphStore.health_check() returned False"
                    return

            driver = getattr(self._store, "driver", None) or getattr(
                self._store, "_driver", None
            )
            if driver is None:
                # some stores keep driver on .client
                driver = getattr(self._store, "client", None)

            if driver is not None:
                self._driver = driver
                with self._driver.session() as session:
                    session.run("RETURN 1 AS ok").consume()
                self._available = True
                return

            self._connect_error = "GraphStore has no driver after connect()"
        except Exception as e:
            self._connect_error = f"GraphStore: {e}"

        # 2) Fallback: raw driver from settings
        try:
            import os
            from neo4j import GraphDatabase

            try:
                from config import settings

                uri = (
                    getattr(settings, "neo4j_uri", None)
                    or getattr(settings, "NEO4J_URI", None)
                    or os.getenv("NEO4J_URI", "bolt://localhost:7687")
                )
                user = (
                    getattr(settings, "neo4j_user", None)
                    or getattr(settings, "NEO4J_USER", None)
                    or os.getenv("NEO4J_USER", "neo4j")
                )
                password = (
                    getattr(settings, "neo4j_password", None)
                    or getattr(settings, "NEO4J_PASSWORD", None)
                    or os.getenv("NEO4J_PASSWORD", "password")
                )
            except Exception:
                uri = os.getenv("NEO4J_URI", "bolt://localhost:7687")
                user = os.getenv("NEO4J_USER", "neo4j")
                password = os.getenv("NEO4J_PASSWORD", "password")

            self._driver = GraphDatabase.driver(uri, auth=(user, password))
            with self._driver.session() as session:
                session.run("RETURN 1 AS ok").consume()
            self._available = True
            self._connect_error = ""
        except Exception as e:
            self._connect_error = (self._connect_error + f" | driver: {e}").strip(" |")
            self._driver = None
            self._available = False

    def _run(self, cypher: str, **params) -> list[dict[str, Any]]:
        if not self._available or self._driver is None:
            raise GraphUnavailableError(
                self._connect_error or "no executable graph backend"
            )
        with self._driver.session() as session:
            result = session.run(cypher, **params)
            return [dict(r) for r in result]

    def find_dependencies(
        self,
        path: str,
        *,
        direction: str = "out",
        limit: int = 100,
    ) -> List[DependencyEdge]:
        path = normalize_path(path)
        direction = (direction or "out").lower()
        if direction not in ("out", "in"):
            raise ValueError("direction must be 'out' or 'in'")

        # Schema: (Repository)-[:CONTAINS]->(File)-[:IMPORTS]->(File)
        if direction == "out":
            cypher = """
            MATCH (r:Repository {name: $repo})-[:CONTAINS]->(a:File {path: $path})
                -[:IMPORTS]->(b:File)
            RETURN a.path AS source_path, b.path AS target_path
            LIMIT $limit
            """
        else:
            cypher = """
            MATCH (r:Repository {name: $repo})-[:CONTAINS]->(b:File {path: $path})
            MATCH (a:File)-[:IMPORTS]->(b)
            WHERE (r)-[:CONTAINS]->(a)
            RETURN a.path AS source_path, b.path AS target_path
            LIMIT $limit
            """

        rows = self._run(cypher, repo=self.repo_name, path=path, limit=limit)

        kind = "IMPORTS" if direction == "out" else "reverse_IMPORTS"
        edges: List[DependencyEdge] = []
        seen = set()
        for row in rows:
            src = normalize_path(str(row.get("source_path") or ""))
            tgt = normalize_path(str(row.get("target_path") or ""))
            if not src or not tgt:
                continue
            key = (src, tgt)
            if key in seen:
                continue
            seen.add(key)
            edges.append(DependencyEdge(source_path=src, target_path=tgt, kind=kind))
        return edges

    def find_callees(
        self,
        symbol: str,
        *,
        path: Optional[str] = None,
        limit: int = 50,
    ) -> List[CallEdge]:
        return self._call_edges(symbol, path=path, limit=limit, direction="out")

    def find_callers(
        self,
        symbol: str,
        *,
        path: Optional[str] = None,
        limit: int = 50,
    ) -> List[CallEdge]:
        return self._call_edges(symbol, path=path, limit=limit, direction="in")

    def _call_edges(
        self,
        symbol: str,
        *,
        path: Optional[str],
        limit: int,
        direction: str,
    ) -> List[CallEdge]:
        symbol = (symbol or "").strip()
        if not symbol:
            return []
        path = normalize_path(path) if path else None

        params: dict = {
            "repo": self.repo_name,
            "symbol": symbol,
            "limit": limit,
        }
        if path:
            params["path"] = path

        if direction == "out":
            queries = [
                # File CONTAINS Symbol CALLS
                """
                MATCH (r:Repository {name: $repo})-[:CONTAINS]->(f:File)
                      -[:CONTAINS]->(caller:Symbol {name: $symbol})
                      -[:CALLS]->(callee:Symbol)
                WHERE $path IS NULL OR f.path = $path
                OPTIONAL MATCH (cf:File)-[:CONTAINS]->(callee)
                RETURN caller.name AS caller, callee.name AS callee,
                       f.path AS caller_path, cf.path AS callee_path
                LIMIT $limit
                """,
                """
                MATCH (caller:Symbol {name: $symbol})-[:CALLS]->(callee:Symbol)
                WHERE ($path IS NULL OR caller.path = $path OR caller.file_path = $path)
                  AND (caller.repo = $repo OR caller.repository = $repo OR true)
                RETURN caller.name AS caller, callee.name AS callee,
                       coalesce(caller.path, caller.file_path) AS caller_path,
                       coalesce(callee.path, callee.file_path) AS callee_path
                LIMIT $limit
                """,
            ]
        else:
            queries = [
                """
                MATCH (r:Repository {name: $repo})-[:CONTAINS]->(f:File)
                      -[:CONTAINS]->(callee:Symbol {name: $symbol})
                MATCH (caller:Symbol)-[:CALLS]->(callee)
                WHERE $path IS NULL OR f.path = $path
                OPTIONAL MATCH (cf:File)-[:CONTAINS]->(caller)
                RETURN caller.name AS caller, callee.name AS callee,
                       cf.path AS caller_path, f.path AS callee_path
                LIMIT $limit
                """,
                """
                MATCH (caller:Symbol)-[:CALLS]->(callee:Symbol {name: $symbol})
                WHERE ($path IS NULL OR callee.path = $path OR callee.file_path = $path)
                RETURN caller.name AS caller, callee.name AS callee,
                       coalesce(caller.path, caller.file_path) AS caller_path,
                       coalesce(callee.path, callee.file_path) AS callee_path
                LIMIT $limit
                """,
            ]

        # neo4j may not like $path IS NULL the same way — pass path always
        if path is None:
            # rewrite simpler without path filter for first query attempts
            params["path"] = None

        rows = []
        for cypher in queries:
            try:
                # For IS NULL checks, use two variants when path is None
                if path is None and "$path IS NULL OR" in cypher:
                    # strip path filter manually via alternate query without path
                    continue
                rows = self._run(cypher, **params)
                if rows:
                    break
            except Exception:
                continue

        if path is None and not rows:
            # path-free queries
            if direction == "out":
                cypher = """
                MATCH (caller:Symbol {name: $symbol})-[:CALLS]->(callee:Symbol)
                RETURN caller.name AS caller, callee.name AS callee,
                       coalesce(caller.path, caller.file_path) AS caller_path,
                       coalesce(callee.path, callee.file_path) AS callee_path
                LIMIT $limit
                """
            else:
                cypher = """
                MATCH (caller:Symbol)-[:CALLS]->(callee:Symbol {name: $symbol})
                RETURN caller.name AS caller, callee.name AS callee,
                       coalesce(caller.path, caller.file_path) AS caller_path,
                       coalesce(callee.path, callee.file_path) AS callee_path
                LIMIT $limit
                """
            try:
                rows = self._run(cypher, repo=self.repo_name, symbol=symbol, limit=limit)
            except Exception as e:
                raise GraphUnavailableError(str(e))

        edges: List[CallEdge] = []
        for row in rows:
            caller = row.get("caller") or ""
            callee = row.get("callee") or ""
            if not caller or not callee:
                continue
            edges.append(
                CallEdge(
                    caller=caller,
                    callee=callee,
                    caller_path=row.get("caller_path"),
                    callee_path=row.get("callee_path"),
                )
            )
        return edges

    def close(self) -> None:
        try:
            if self._store is not None and hasattr(self._store, "close"):
                self._store.close()
        except Exception:
            pass