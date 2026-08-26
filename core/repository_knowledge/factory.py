from __future__ import annotations

from typing import Optional

from core.repository_knowledge.graphify_mcp import GraphifyMCPProvider
from core.repository_knowledge.paths import ensure_graph_exists
from core.repository_knowledge.provider import RepositoryKnowledgeProvider


def get_knowledge_provider(repo: Optional[str] = None) -> RepositoryKnowledgeProvider:
    """
    Build a Graphify-backed knowledge provider.

    If repo is given (owner/name), resolve:
        repos/<owner_name>/graphify-out/graph.json

    If repo is None, fall back to settings.graphify_graph_path (manual override).
    """
    from config import settings

    if repo:
        graph_path = str(ensure_graph_exists(repo))
    else:
        override = getattr(settings, "graphify_graph_path", "") or ""
        if not override:
            raise ValueError(
                "No repo provided and GRAPHIFY_GRAPH_PATH is empty. "
                "Pass owner/repo or set an explicit graph path."
            )
        graph_path = override

    return GraphifyMCPProvider(
        graph_path=graph_path,
        transport=getattr(settings, "graphify_transport", "stdio"),
        http_url=getattr(settings, "graphify_http_url", "http://localhost:8080/mcp"),
        python_executable=getattr(settings, "graphify_python", "python"),
        project_path=None,
    )