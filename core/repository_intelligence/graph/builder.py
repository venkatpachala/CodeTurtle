from __future__ import annotations

from typing import Iterable
from neo4j import Driver

from core.repository_intelligence.models import RepositorySnapshot, ParsedFile, Symbol
from core.repository_intelligence.graph.store import GraphStore
from core.repository_intelligence.models.node import NodeID


class GraphBuilder:
    """
    Phase 2: Materialize RepositorySnapshot into Neo4j.
    Idempotent — uses MERGE on node_id.
    """

    def __init__(self, store: GraphStore | None = None):
        self.store = store or GraphStore()

    def build(self, snapshot: RepositorySnapshot, clear_existing: bool = False) -> dict:
        driver = self.store.connect()
        self.store.ensure_constraints()

        stats = {
            "files": 0,
            "symbols": 0,
            "contains_file": 0,
            "contains_symbol": 0,
        }

        with driver.session() as session:
            if clear_existing:
                session.run(
                    """
                    MATCH (n)
                    WHERE n.repo_name = $repo
                    DETACH DELETE n
                    """,
                    repo=snapshot.repo_name,
                )

            # Repository node
            repo_id = NodeID.from_parts(snapshot.repo_name, "repository", snapshot.repo_name)
            session.run(
                """
                MERGE (r:Repository {node_id: $node_id})
                SET r.repo_name = $repo_name,
                    r.local_path = $local_path,
                    r.languages = $languages,
                    r.total_files = $total_files
                """,
                node_id=str(repo_id),
                repo_name=snapshot.repo_name,
                local_path=snapshot.local_path,
                languages=snapshot.languages,
                total_files=snapshot.total_files,
            )

            for pf in snapshot.files:
                self._upsert_file(session, snapshot.repo_name, str(repo_id), pf, stats)

        return stats

    def _upsert_file(self, session, repo_name: str, repo_node_id: str, pf: ParsedFile, stats: dict):
        file_id = NodeID.from_parts(repo_name, "file", pf.path)

        session.run(
            """
            MERGE (f:File {node_id: $node_id})
            SET f.repo_name = $repo_name,
                f.path = $path,
                f.language = $language,
                f.line_count = $line_count,
                f.size_bytes = $size_bytes
            """,
            node_id=str(file_id),
            repo_name=repo_name,
            path=pf.path,
            language=pf.language,
            line_count=pf.line_count,
            size_bytes=pf.size_bytes,
        )
        stats["files"] += 1

        # Repository -[:CONTAINS]-> File
        session.run(
            """
            MATCH (r:Repository {node_id: $repo_id})
            MATCH (f:File {node_id: $file_id})
            MERGE (r)-[:CONTAINS]->(f)
            """,
            repo_id=repo_node_id,
            file_id=str(file_id),
        )
        stats["contains_file"] += 1

        for sym in pf.symbols:
            self._upsert_symbol(session, repo_name, str(file_id), sym, stats)

    def _upsert_symbol(self, session, repo_name: str, file_node_id: str, sym: Symbol, stats: dict):
        session.run(
            """
            MERGE (s:Symbol {node_id: $node_id})
            SET s.repo_name = $repo_name,
                s.name = $name,
                s.qualified_name = $qualified_name,
                s.kind = $kind,
                s.language = $language,
                s.file_path = $file_path,
                s.parent_qualified_name = $parent,
                s.start_line = $start_line,
                s.end_line = $end_line,
                s.docstring = $docstring
            """,
            node_id=str(sym.node_id),
            repo_name=repo_name,
            name=sym.name,
            qualified_name=sym.qualified_name,
            kind=sym.kind,
            language=sym.language,
            file_path=sym.file_path,
            parent=sym.parent_qualified_name,
            start_line=sym.span.start_line if sym.span else None,
            end_line=sym.span.end_line if sym.span else None,
            docstring=(sym.docstring or "")[:2000],
        )
        stats["symbols"] += 1

        # File -[:CONTAINS]-> Symbol
        session.run(
            """
            MATCH (f:File {node_id: $file_id})
            MATCH (s:Symbol {node_id: $sym_id})
            MERGE (f)-[:CONTAINS]->(s)
            """,
            file_id=file_node_id,
            sym_id=str(sym.node_id),
        )
        stats["contains_symbol"] += 1