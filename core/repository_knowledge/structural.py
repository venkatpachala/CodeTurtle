from __future__ import annotations

from typing import List, Optional

from core.repository_knowledge.factory import get_knowledge_provider
from core.repository_knowledge.graphify_mcp import GraphifyMCPError
from core.repository_knowledge.paths import resolve_graph_path
from core.repository_knowledge.provider import RepositoryKnowledgeProvider


def graph_available(repo: str) -> bool:
    try:
        return resolve_graph_path(repo).exists()
    except Exception:
        return False


def get_provider_if_available(repo: str) -> Optional[RepositoryKnowledgeProvider]:
    if not graph_available(repo):
        return None
    try:
        return get_knowledge_provider(repo=repo)
    except Exception:
        return None


def build_structural_context(
    repo: str,
    *,
    pr_title: str = "",
    pr_body: str = "",
    files_changed: Optional[List[str]] = None,
    provider: Optional[RepositoryKnowledgeProvider] = None,
) -> str:
    """
    Ask Graphify for structural context useful for a PR review.
    Returns plain text. Empty string on any failure (safe fallback).
    """
    files_changed = files_changed or []

    try:
        provider = provider or get_provider_if_available(repo)
        if provider is None:
            return ""

        sections: List[str] = []

        # 1) High-level structural query from PR intent
        question = _build_question(pr_title, pr_body, files_changed)
        try:
            q = provider.query(question, depth=3)
            if q.raw_text.strip():
                sections.append("### Graphify structural query\n" + q.raw_text.strip())
        except GraphifyMCPError:
            pass

        # 2) Per changed file: try node lookup + neighbors (best-effort)
        file_bits: List[str] = []
        for path in files_changed[:8]:
            label = _file_label(path)
            try:
                node = provider.get_node(label)
                neighbors = provider.get_neighbors(label)
                chunk = f"#### {path}\n"
                if node and node.raw.get("text"):
                    chunk += node.raw["text"].strip() + "\n"
                if neighbors.raw_text.strip():
                    chunk += neighbors.raw_text.strip() + "\n"
                if chunk.strip() != f"#### {path}":
                    file_bits.append(chunk.strip())
            except GraphifyMCPError:
                continue

        if file_bits:
            sections.append(
                "### Graphify file neighborhood\n" + "\n\n".join(file_bits)
            )

        # 3) Light architecture signal
        try:
            gods = provider.god_nodes(top_n=8)
            if gods.strip():
                sections.append("### Graphify god nodes\n" + gods.strip())
        except Exception:
            pass

        if not sections:
            return ""

        return (
            "## Structural context (Graphify)\n\n"
            + "\n\n".join(sections)
        )

    except Exception:
        # Never break the review pipeline
        return ""


def _build_question(title: str, body: str, files: List[str]) -> str:
    parts = []
    if title:
        parts.append(title)
    if body:
        parts.append(body[:500])
    if files:
        parts.append("Changed files: " + ", ".join(files[:12]))
    text = " | ".join(parts).strip()
    if not text:
        return "what are the core modules and main dependency relationships?"
    return f"what structural context is relevant for this change: {text}"


def _file_label(path: str) -> str:
    # Graphify nodes are often filename / symbol oriented; try basename first
    p = path.replace("\\", "/").strip("/")
    base = p.split("/")[-1]
    return base or p