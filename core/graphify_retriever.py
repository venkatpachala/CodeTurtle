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
    ) -> List[Document]:
        files_changed = files_changed or []
        docs: List[Document] = []

        # Main structural package
        structural = build_structural_context(
            self.repo_name,
            pr_title=pr_title or query,
            pr_body=pr_body,
            files_changed=files_changed,
            provider=self.provider,
        )
        if structural.strip():
            docs.append(
                Document(
                    page_content=structural,
                    metadata={"source": "graphify", "type": "structural_context"},
                )
            )

        # Extra focused queries (best-effort)
        extra_questions = [
            query.strip(),
            f"impact of changes in: {', '.join(files_changed[:10])}" if files_changed else "",
        ]
        for q in extra_questions:
            if not q:
                continue
            try:
                result = self.provider.query(q, depth=3)
                if result.raw_text.strip():
                    docs.append(
                        Document(
                            page_content=result.raw_text,
                            metadata={"source": "graphify", "type": "query_graph", "question": q},
                        )
                    )
            except GraphifyMCPError:
                continue

        # Optional PR impact
        # (caller can pass pr number later; skip if unknown)

        print(f"[GraphifyRetriever] Returning {len(docs)} graph documents")
        return docs[: max(k, len(docs))]