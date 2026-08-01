from __future__ import annotations
import os
from typing import Optional
from neo4j import GraphDatabase, Driver


class GraphStore:
    """
    Thin Neo4j wrapper for Repository Intelligence v1.
    """

    def __init__(
        self,
        uri: Optional[str] = None,
        user: Optional[str] = None,
        password: Optional[str] = None,
    ):
        self.uri = uri or os.getenv("NEO4J_URI", "bolt://127.0.0.1:7687")
        self.user = user or os.getenv("NEO4J_USER", "neo4j")
        self.password = password or os.getenv("NEO4J_PASSWORD", "codeturtle123")
        self._driver: Optional[Driver] = None

    def connect(self) -> Driver:
        if self._driver is None:
            self._driver = GraphDatabase.driver(
                self.uri,
                auth=(self.user, self.password),
            )
        return self._driver

    def close(self):
        if self._driver:
            self._driver.close()
            self._driver = None

    def health_check(self) -> bool:
        driver = self.connect()
        try:
            with driver.session() as session:
                result = session.run("RETURN 1 AS ok")
                record = result.single()
                return record is not None and record["ok"] == 1
        except Exception as e:
            print(f"[GraphStore] Health check failed: {e}")
            return False

    def ensure_constraints(self):
        """
        Create uniqueness constraint on node_id.
        Safe to call multiple times.
        """
        driver = self.connect()
        queries = [
            "CREATE CONSTRAINT IF NOT EXISTS FOR (n:Entity) REQUIRE n.node_id IS UNIQUE",
            "CREATE CONSTRAINT IF NOT EXISTS FOR (n:File) REQUIRE n.node_id IS UNIQUE",
            "CREATE CONSTRAINT IF NOT EXISTS FOR (n:Symbol) REQUIRE n.node_id IS UNIQUE",
        ]
        with driver.session() as session:
            for q in queries:
                session.run(q)
        print("[GraphStore] Constraints ensured.")