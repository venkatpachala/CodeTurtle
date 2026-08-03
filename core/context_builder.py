from typing import List, Union
from langchain_core.documents import Document

from core.evidence import Evidence, EvidencePackage


class ContextBuilder:
    """Builds a rich EvidencePackage from PR understanding + retrieved documents."""

    @staticmethod
    def build(
        query: str,
        pr_understanding: dict,
        documents: List[Union[Document, Evidence]]
    ) -> EvidencePackage:
        evidences = []
        affected_files = set()
        related_symbols = set()

        for doc in documents:
            # Handle both LangChain Document and our Evidence model
            if isinstance(doc, Evidence):
                evidence = doc  # already an Evidence object
            else:
                # Old LangChain Document path
                meta = getattr(doc, "metadata", {}) or {}
                evidence = Evidence(
                    path=meta.get("path", "unknown"),
                    chunk_type=meta.get("chunk_type", "module"),
                    start_line=meta.get("start_line"),
                    end_line=meta.get("end_line"),
                    symbols=meta.get("symbols", []) or [],
                    retrieval_type=meta.get("retrieval_type", "vector"),
                    content=getattr(doc, "page_content", ""),
                    score=meta.get("score", 0.0),
                    source_query=meta.get("source_query"),
                    query_category=meta.get("query_category"),
                    query_weight=meta.get("query_weight"),
                )

            evidences.append(evidence)
            affected_files.add(evidence.path)
            related_symbols.update(evidence.symbols or [])

        package = EvidencePackage(
            query=query,
            pr_understanding=pr_understanding or {},
            evidences=evidences,
            affected_files=sorted(list(affected_files)),
            related_symbols=sorted(list(related_symbols)),
        )

        package.summary = ContextBuilder._build_summary(package)
        return package

    # core/context_builder.py (add or extend)

    def format_evidence_for_agents(evidence_package, max_chars: int = 12000) -> str:
        lines = ["### Retrieved evidence"]
        evidences = getattr(evidence_package, "evidences", None) or []
        used = 0
        for i, ev in enumerate(evidences, 1):
            path = getattr(ev, "path", "") or ""
            content = (getattr(ev, "content", None) or getattr(ev, "page_content", "") or "")[:2000]
            block = f"\n[{i}] path={path}\n{content}\n"
            if used + len(block) > max_chars:
                break
            lines.append(block)
            used += len(block)
        if len(lines) == 1:
            lines.append("\n(No evidence retrieved — do not invent file contents.)")
        return "".join(lines)

    @staticmethod
    def _build_summary(package: EvidencePackage) -> str:
        lines = [
            f"PR Summary: {package.pr_understanding.get('summary', 'N/A')}",
            f"Risk Level: {package.pr_understanding.get('risk_level', 'unknown')}",
            f"Change Types: {', '.join(package.pr_understanding.get('change_type', []))}",
            f"Affected Files: {len(package.affected_files)}",
            f"Related Symbols: {', '.join(package.related_symbols[:10])}",
            "",
            "Key Evidence:"
        ]

        for i, ev in enumerate(package.evidences[:6]):
            lines.append(
                f"{i+1}. {ev.path} ({ev.chunk_type or 'module'}) "
                f"lines {ev.start_line}-{ev.end_line} "
                f"symbols={ev.symbols}"
            )

        return "\n".join(lines)

    @staticmethod
    def to_agent_context(package: EvidencePackage, max_chars: int = 12000) -> str:
        """Convert EvidencePackage into a text context for LLM agents."""

        parts = [
            "=== PR UNDERSTANDING ===",
            package.summary,
            "",
            "=== RETRIEVED EVIDENCE ===",
        ]

        current_length = len("\n".join(parts))

        for ev in package.evidences:
            block = f"""
--- File: {ev.path} ---
Type: {ev.chunk_type or 'module'}
Lines: {ev.start_line}-{ev.end_line}
Symbols: {', '.join(ev.symbols) if ev.symbols else 'None'}

{ev.content}
"""
            if current_length + len(block) > max_chars:
                break
            parts.append(block)
            current_length += len(block)

        return "\n".join(parts)