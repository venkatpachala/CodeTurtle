"""PR evidence: read-only use of Repository Intelligence artifacts."""
from __future__ import annotations

from core.graphify_retriever import GraphifyRetriever
from core.context_builder import ContextBuilder


def build_evidence_package(state: dict) -> dict:
    """
    Single link from PR Intelligence → Repository Intelligence.
    Reads: Graphify structural context (via GraphifyRetriever).
    """
    repo = state.get("repo") or ""
    title = state.get("title") or ""
    body = state.get("body") or ""
    files_changed = state.get("files_changed") or []
    pr_understanding = state.get("pr_understanding") or {}

    query = f"{title}\n{body}".strip() or " ".join(files_changed[:20])

    try:
        retriever = GraphifyRetriever(repo)
        docs = retriever.retrieve(
            query=query,
            pr_title=title,
            pr_body=body,
            files_changed=list(files_changed),
            k=8,
        )
    except Exception as e:
        print(f"[build_evidence_package] GraphifyRetriever fallback/skipped: {e}")
        docs = []

    package = ContextBuilder.build(
        query=query,
        pr_understanding=pr_understanding if isinstance(pr_understanding, dict) else {},
        documents=docs,
    )

    if hasattr(ContextBuilder, "to_agent_context"):
        rich_context = ContextBuilder.to_agent_context(package)
    else:
        rich_context = "\n\n".join(d.page_content for d in docs if d.page_content)

    return {
        "evidence_package": package,
        "context_from_kb": rich_context or state.get("context_from_kb", ""),
        "traces": [{
            "agent": "BuildEvidencePackage",
            "output": f"evidence built via GraphifyRetriever; files_changed={len(files_changed)}",
        }],
    }