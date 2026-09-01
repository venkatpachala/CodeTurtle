from __future__ import annotations

from typing import List, Optional

from langchain_core.documents import Document

from core.repository_knowledge.structural import build_structural_context, graph_available
from core.repository_knowledge.factory import get_knowledge_provider
from core.repository_knowledge.graphify_mcp import GraphifyMCPError


class GraphifyRetriever:
    """Graphify-only retrieval. No Qdrant."""

    def __init__(self, repo_name: str):
        self.repo_name = repo_name
        if not graph_available(repo_name):
            raise FileNotFoundError(
                f"Graphify graph missing for {repo_name}. "
                f"Run: cd repos/{repo_name.replace('/', '_')} && graphify . --code-only"
            )
        self.provider = get_knowledge_provider(repo=repo_name)

    def retrieve(
        self,
        query: str,
        k: int = 6,
        *,
        pr_title: str = "",
        pr_body: str = "",
        files_changed: Optional[List[str]] = None,
        full_diff: str = "",
        pr_number: Optional[int] = None,
    ) -> List[Document]:
        files_changed = files_changed or []
        docs: List[Document] = []

        structural = build_structural_context(
            self.repo_name,
            pr_title=pr_title or query,
            pr_body=pr_body,
            files_changed=files_changed,
            full_diff=full_diff,
            pr_number=pr_number,
            provider=self.provider,
        )
        if structural.strip():
            docs.append(
                Document(
                    page_content=structural,
                    metadata={"source": "graphify", "type": "structural_context"},
                )
            )

        # One extra graph query from the caller question only if non-empty
        if query and query.strip():
            try:
                result = self.provider.query(query.strip(), depth=3)
                if result.raw_text.strip():
                    docs.append(
                        Document(
                            page_content=result.raw_text,
                            metadata={"source": "graphify", "type": "query_graph"},
                        )
                    )
            except GraphifyMCPError:
                pass

        print(f"[GraphifyRetriever] Returning {len(docs)} graph documents")
        return docs

    def investigate_file(
        self,
        path: str,
        *,
        symbol: Optional[str] = None,
    ) -> List[dict]:
        """Targeted hop: node + neighbors for one changed path. Not a full retrieve."""
        return self.provider.investigate_file(path, symbol=symbol)