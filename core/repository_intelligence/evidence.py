"""PR evidence: read-only use of Repository Intelligence artifacts."""
from __future__ import annotations

from core.hybrid_retriever import HybridRetriever
from core.context_builder import ContextBuilder


def build_evidence_package(state: dict) -> dict:
    """
    Single link from PR Intelligence → Repository Intelligence.

    Reads: Qdrant + Neo4j IMPORTS (via HybridRetriever).
    Never recompiles the repository.
    """
    repo = state.get("repo") or ""
    title = state.get("title") or ""
    body = state.get("body") or ""
    files_changed = state.get("files_changed") or []
    pr_understanding = state.get("pr_understanding") or {}

    query = f"{title}\n{body}".strip() or " ".join(files_changed[:20])

    retriever = HybridRetriever(repo, kb=state.get("kb"))
    package = retriever.retrieve(
        query=query,
        pr_understanding=pr_understanding if isinstance(pr_understanding, dict) else {},
        files_changed=list(files_changed),
        k=8,
    )

    # Prefer your existing ContextBuilder API
    if hasattr(ContextBuilder, "to_agent_context"):
        rich_context = ContextBuilder.to_agent_context(package)
    else:
        rich_context = ContextBuilder.build(
            query=query,
            pr_understanding=pr_understanding if isinstance(pr_understanding, dict) else {},
            documents=getattr(package, "evidences", None) or [],
        )
        if hasattr(rich_context, "to_string"):
            rich_context = rich_context.to_string()
        elif not isinstance(rich_context, str):
            rich_context = str(rich_context)

    dep = getattr(package, "dependency_context", None) or getattr(package, "extra_context", None)
    if dep:
        rich_context = f"{rich_context}\n\n{dep}"

    expansion = getattr(retriever, "_last_graph_expansion", []) or []

    return {
        "evidence_package": package,
        "context_from_kb": rich_context,
        "traces": [{
            "agent": "BuildEvidencePackage",
            "output": (
                f"evidence built; files_changed={len(files_changed)}; "
                f"graph_expansion={expansion[:10]}"
            ),
        }],
    }