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
    full_diff: str = "",
    pr_number: Optional[int] = None,
    provider: Optional[RepositoryKnowledgeProvider] = None,
) -> str:
    files_changed = files_changed or []
    try:
        provider = provider or get_provider_if_available(repo)
        if provider is None:
            return ""

        sections: List[str] = []

        # A) Explicit change inventory (deterministic — no LLM)
        inventory = _change_inventory(files_changed, full_diff)
        if inventory:
            sections.append("### Change inventory (deterministic)\n" + inventory)

        # B) Graph query grounded in files + title
        question = _build_question(pr_title, pr_body, files_changed, full_diff)
        try:
            q = provider.query(question, depth=3)
            if q.raw_text.strip():
                sections.append("### Graphify structural query\n" + q.raw_text.strip())
        except GraphifyMCPError:
            pass

        # C) Neighborhood for each changed path
        file_bits: List[str] = []
        for path in files_changed[:12]:
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
            sections.append("### Graphify file neighborhood\n" + "\n\n".join(file_bits))

        # D) PR impact if Graphify supports it
        if pr_number is not None:
            try:
                impact = provider.get_pr_impact(pr_number, repo=repo)
                if impact.raw_text.strip():
                    sections.append("### Graphify PR impact\n" + impact.raw_text.strip())
            except Exception:
                pass

        # E) Diff excerpt (hard grounding for agents)
        diff_excerpt = _diff_excerpt(full_diff, max_chars=12000)
        if diff_excerpt:
            sections.append("### PR diff excerpt\n```diff\n" + diff_excerpt + "\n```")

        if not sections:
            return ""
        return "## Structural context (Graphify)\n\n" + "\n\n".join(sections)
    except Exception:
        return ""


def _change_inventory(files: List[str], full_diff: str) -> str:
    lines = []
    if files:
        lines.append("Changed files:")
        for f in files[:50]:
            lines.append(f"- {f}")
    else:
        lines.append("Changed files: (none listed)")

    # Cheap lockfile / dependency detection
    lock_files = [f for f in files if f.endswith("package-lock.json") or f.endswith("yarn.lock") or f.endswith("pnpm-lock.yaml")]
    manifest_files = [f for f in files if f.endswith("package.json") or f.endswith("pyproject.toml") or f.endswith("requirements.txt")]
    code_files = [f for f in files if f.endswith((".py", ".ts", ".tsx", ".js", ".jsx", ".go", ".rs", ".java"))]

    lines.append("")
    lines.append(f"Lockfiles changed: {len(lock_files)} → {lock_files[:10]}")
    lines.append(f"Manifests changed: {len(manifest_files)} → {manifest_files[:10]}")
    lines.append(f"Source code files changed: {len(code_files)} → {code_files[:20]}")

    if lock_files and not code_files:
        lines.append("")
        lines.append(
            "CLASSIFICATION: dependency/lockfile-only change. "
            "Do NOT invent feature work, architecture refactors, or unrelated API changes. "
            "Focus on version bumps, lockfile consistency, engine constraints, and install determinism."
        )
    return "\n".join(lines)


def _build_question(title: str, body: str, files: List[str], full_diff: str = "") -> str:
    parts = []
    if title:
        parts.append(f"PR title: {title}")
    if body:
        parts.append(f"PR body: {body[:400]}")
    if files:
        parts.append("Changed files: " + ", ".join(files[:20]))
    # tiny signal from diff headers
    diff_files = []
    for line in (full_diff or "").splitlines():
        if line.startswith("+++ b/") or line.startswith("--- a/"):
            diff_files.append(line[6:])
    if diff_files:
        parts.append("Diff paths: " + ", ".join(dict.fromkeys(diff_files)[:20]))
    text = " | ".join(parts).strip()
    if not text:
        return "what modules are most central in this repository?"
    return (
        "Given this PR, what related modules, imports, and call relationships matter? "
        + text
    )


def _diff_excerpt(full_diff: str, max_chars: int = 12000) -> str:
    if not full_diff:
        return ""
    if len(full_diff) <= max_chars:
        return full_diff
    head = full_diff[: max_chars // 2]
    tail = full_diff[-(max_chars // 2) :]
    return head + "\n\n... [diff truncated] ...\n\n" + tail

def _file_label(path: str) -> str:
    # Graphify nodes are often filename / symbol oriented; try basename first
    p = path.replace("\\", "/").strip("/")
    base = p.split("/")[-1]
    return base or p