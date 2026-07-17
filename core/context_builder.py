from typing import List
from langchain_core.documents import Document

from core.evidence import EvidencePackage


class ContextBuilder:
    """Builds a rich EvidencePackage from PR understanding + retrieved documents."""

    @staticmethod
    def build(
        query: str,
        pr_understanding: dict,
        documents: List[Document]
    ) -> EvidencePackage:
        from core.evidence import Evidence, EvidencePackage

        evidences = []
        affected_files = set()
        related_symbols = set()

        for doc in documents:
            meta = doc.metadata or {}

            path = meta.get("path", "unknown")
            symbols = meta.get("symbols", []) or []
            chunk_type = meta.get("chunk_type", "module")

            evidence = Evidence(
                path=path,
                chunk_type=chunk_type,
                start_line=meta.get("start_line"),
                end_line=meta.get("end_line"),
                symbols=symbols,
                retrieval_type=meta.get("retrieval_type", "vector"),
                content=doc.page_content,
                score=meta.get("score", 0.0),
            )

            evidences.append(evidence)
            affected_files.add(path)
            related_symbols.update(symbols)

        package = EvidencePackage(
            query=query,
            pr_understanding=pr_understanding or {},
            evidences=evidences,
            affected_files=sorted(list(affected_files)),
            related_symbols=sorted(list(related_symbols)),
        )

        # Simple summary for agents
        package.summary = ContextBuilder._build_summary(package)

        return package

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
                f"{i+1}. {ev.path} ({ev.chunk_type}) "
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
Type: {ev.chunk_type}
Lines: {ev.start_line}-{ev.end_line}
Symbols: {', '.join(ev.symbols) if ev.symbols else 'None'}

{ev.content}
"""
            if current_length + len(block) > max_chars:
                break
            parts.append(block)
            current_length += len(block)

        return "\n".join(parts)